"""
T7 — Geocoding Service (2GIS + Nominatim fallback).

Runs in PARALLEL with T5 and T6.
  • Primary: 2GIS API for Kazakhstan street-level accuracy
  • Fallback: Nominatim (OpenStreetMap) via geopy
  • Cache: geocoding_cache table

Address resolution rules:
  1) No country:
       - city given → search for that city among CIS countries, pick random match
       - no city   → all null (even if street/house exist)
  2) Country given:
       - no city → center of the country's capital
       - city but no street → center of city
       - city+street but no house → center of city  (street-only geocoding unreliable)
       - city+street+house → full geocode to coordinate
"""

import logging
import random
import uuid
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sse_manager import sse_manager
from app.models.models import (
    GeocodingCache, ProcessingState, ProcessingStageEnum,
    StageStatusEnum, Ticket, AddressStatusEnum,
)
from app.models.schemas import GeocodingResult

log = logging.getLogger("pipeline.geo")
settings = get_settings()

# Capital city coordinates (CIS countries)
CAPITAL_COORDS = {
    "казахстан": (51.1694, 71.4491),   # Astana
    "kazakhstan": (51.1694, 71.4491),
    "россия": (55.7558, 37.6173),       # Moscow
    "russia": (55.7558, 37.6173),
    "узбекистан": (41.2995, 69.2401),   # Tashkent
    "uzbekistan": (41.2995, 69.2401),
    "украина": (50.4501, 30.5234),       # Kyiv
    "ukraine": (50.4501, 30.5234),
    "азербайджан": (40.4093, 49.8671),   # Baku
    "azerbaijan": (40.4093, 49.8671),
    "кыргызстан": (42.8746, 74.5698),   # Bishkek
    "kyrgyzstan": (42.8746, 74.5698),
    "таджикистан": (38.5598, 68.7738),  # Dushanbe
    "tajikistan": (38.5598, 68.7738),
    "туркменистан": (37.9601, 58.3261), # Ashgabat
    "turkmenistan": (37.9601, 58.3261),
    "беларусь": (53.9006, 27.5590),     # Minsk
    "belarus": (53.9006, 27.5590),
    "молдова": (47.0105, 28.8638),      # Chisinau
    "moldova": (47.0105, 28.8638),
    "грузия": (41.7151, 44.8271),       # Tbilisi
    "georgia": (41.7151, 44.8271),
    "армения": (40.1872, 44.5152),      # Yerevan
    "armenia": (40.1872, 44.5152),
}

# All CIS country names for city search fallback
CIS_COUNTRIES = [
    "Казахстан", "Россия", "Узбекистан", "Украина",
    "Кыргызстан", "Таджикистан", "Беларусь", "Молдова",
    "Грузия", "Армения", "Азербайджан", "Туркменистан",
]

# Astana/Almaty for 50/50 split (international users)
ASTANA_COORDS = (51.1694, 71.4491)
ALMATY_COORDS = (43.2220, 76.8512)
_unknown_counter = 0

_KZ_NAMES = {"казахстан", "kazakhstan", "кз", "kz"}


def _is_kazakhstan(country: str) -> bool:
    return country.strip().lower() in _KZ_NAMES


def _build_address_string(
    country: str | None,
    region: str | None,
    city: str | None,
    street: str | None,
    house: str | None,
) -> str:
    """Build a geocodable address from components."""
    parts = [p.strip() for p in [country, region, city, street, house] if p and p.strip()]
    return ", ".join(parts)


async def _geocode_2gis(address: str) -> tuple[float, float] | None:
    """Geocode via 2GIS API."""
    if not settings.TWOGIS_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://catalog.api.2gis.com/3.0/items/geocode",
                params={
                    "q": address,
                    "fields": "items.point",
                    "key": settings.TWOGIS_API_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()

        items = data.get("result", {}).get("items", [])
        if items:
            point = items[0].get("point")
            if point:
                return (float(point["lat"]), float(point["lon"]))
    except Exception:
        pass
    return None


async def _geocode_nominatim(address: str) -> tuple[float, float] | None:
    """Geocode via Nominatim (OpenStreetMap) — fallback."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": address,
                    "format": "json",
                    "limit": 1,
                },
                headers={
                    "User-Agent": "FIRE-Geocoder/1.0",
                },
            )
            response.raise_for_status()
            data = response.json()

        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        pass
    return None


async def geocode_address(
    country: str | None,
    region: str | None,
    city: str | None,
    street: str | None,
    house: str | None,
    db: AsyncSession | None = None,
) -> GeocodingResult:
    """
    Geocode an address following the cascading fallback rules.

    Rule 1 — no country:
      • city present → search "{city}" among CIS countries via Nominatim, pick
        a random match from the results.
      • no city → all null (lat/lon = None, status='unknown')

    Rule 2 — country present:
      • no city → center of that country's capital
      • city, no street → center of city
      • city + street, no house → center of city
      • city + street + house → full geocode
    """
    country_s = (country or "").strip() or None
    city_s = (city or "").strip() or None
    street_s = (street or "").strip() or None
    house_s = (house or "").strip() or None
    region_s = (region or "").strip() or None

    # ── RULE 1: NO COUNTRY ──
    if not country_s:
        if city_s:
            # Search city among CIS countries
            log.info("  [GEO] no country — searching '%s' in CIS", city_s)
            return await _search_city_in_cis(city_s, db)
        else:
            # No country, no city → unknown
            log.info("  [GEO] no country, no city → null coords")
            return GeocodingResult(
                latitude=None,
                longitude=None,
                provider="no_address",
                address_status="unknown",
                explanation="Координаты не определены: страна и населённый пункт не указаны",
            )

    # ── RULE 2: COUNTRY PRESENT ──
    global _unknown_counter

    # International (non-KZ) → 50/50 Almaty/Astana
    if not _is_kazakhstan(country_s):
        _unknown_counter += 1
        coords = ASTANA_COORDS if _unknown_counter % 2 == 0 else ALMATY_COORDS
        city_name = "Астана" if _unknown_counter % 2 == 0 else "Алматы"
        log.info("  [GEO] international '%s' → 50/50 Almaty/Astana", country_s)
        return GeocodingResult(
            latitude=coords[0],
            longitude=coords[1],
            provider="international_5050",
            address_status="foreign",
            explanation=f"Иностранный адрес ({country_s}): маршрутизация в ближайший офис {city_name}",
        )

    # Kazakhstan — cascade: country → city → street → house
    if not city_s:
        # Country only → capital center (Astana)
        c_lower = country_s.lower()
        coords = CAPITAL_COORDS.get(c_lower, ASTANA_COORDS)
        log.info("  [GEO] KZ, no city → capital center")
        return GeocodingResult(
            latitude=coords[0],
            longitude=coords[1],
            provider="capital_fallback",
            address_status="partial",
            explanation="Населённый пункт не указан — использованы координаты столицы (Астана)",
        )

    if not street_s:
        # Country + city, no street → center of city
        log.info("  [GEO] KZ + city '%s', no street → city center", city_s)
        return await _geocode_city_center(country_s, region_s, city_s, db,
            explanation=f"Улица не указана — использован центр города {city_s}")

    if not house_s:
        # Country + city + street, no house → center of city
        log.info("  [GEO] KZ + city + street, no house → city center")
        return await _geocode_city_center(country_s, region_s, city_s, db,
            explanation=f"Номер дома не указан — использован центр города {city_s}")

    # Full address: country + city + street + house → precise geocode
    log.info("  [GEO] full KZ address → precise geocode")
    address_str = _build_address_string(country_s, region_s, city_s, street_s, house_s)
    return await _geocode_full(address_str, country_s, region_s, city_s, db)


async def _search_city_in_cis(
    city: str,
    db: AsyncSession | None = None,
) -> GeocodingResult:
    """Search for a city name + random CIS country via Nominatim."""
    # Try a few random CIS countries to find the city
    shuffled = CIS_COUNTRIES.copy()
    random.shuffle(shuffled)

    for cis_country in shuffled:
        query = f"{city}, {cis_country}"
        cache_key = f"cis_search:{query}"
        if db:
            cached = await _check_cache(cache_key, db)
            if cached:
                if not cached.explanation:
                    cached.explanation = f"Страна не указана — город {city} найден в {cis_country}"
                return cached

        coords = await _geocode_nominatim(query)
        if coords:
            if db:
                await _save_cache(cache_key, coords, "nominatim_cis", db)
            return GeocodingResult(
                latitude=coords[0],
                longitude=coords[1],
                provider="nominatim_cis",
                address_status="partial",
                explanation=f"Страна не указана — город {city} найден в {cis_country}",
            )

    # Could not find city in any CIS country → null
    log.warning("  [GEO] city '%s' not found in any CIS country", city)
    return GeocodingResult(
        latitude=None,
        longitude=None,
        provider="cis_search_failed",
        address_status="unknown",
        explanation=f"Координаты не определены: город {city} не найден в странах СНГ",
    )


async def _geocode_city_center(
    country: str,
    region: str | None,
    city: str,
    db: AsyncSession | None = None,
    explanation: str | None = None,
) -> GeocodingResult:
    """Geocode to the center of a city."""
    query = _build_address_string(country, region, city, None, None)
    if db:
        cached = await _check_cache(query, db)
        if cached:
            if explanation and not cached.explanation:
                cached.explanation = explanation
            return cached

    # Try 2GIS first for KZ
    coords = await _geocode_2gis(query)
    provider = "2gis"
    if not coords:
        coords = await _geocode_nominatim(query)
        provider = "nominatim"

    if coords:
        if db:
            await _save_cache(query, coords, provider, db)
        return GeocodingResult(
            latitude=coords[0],
            longitude=coords[1],
            provider=f"{provider}_city",
            address_status="partial",
            explanation=explanation or f"Использован центр города {city}",
        )

    # City geocoding failed → 50/50 Astana/Almaty
    global _unknown_counter
    _unknown_counter += 1
    fallback = ASTANA_COORDS if _unknown_counter % 2 == 0 else ALMATY_COORDS
    city_name = "Астана" if _unknown_counter % 2 == 0 else "Алматы"
    return GeocodingResult(
        latitude=fallback[0],
        longitude=fallback[1],
        provider="city_geocode_failed",
        address_status="unknown",
        explanation=f"Координаты не определены: город {city} не найден — назначен офис {city_name}",
    )


async def _geocode_full(
    address_str: str,
    country: str,
    region: str | None,
    city: str,
    db: AsyncSession | None = None,
) -> GeocodingResult:
    """Full geocode with 2GIS → Nominatim → city-center fallback."""
    if db:
        cached = await _check_cache(address_str, db)
        if cached:
            return cached

    # Try 2GIS
    coords = await _geocode_2gis(address_str)
    if coords:
        if db:
            await _save_cache(address_str, coords, "2gis", db)
        return GeocodingResult(
            latitude=coords[0],
            longitude=coords[1],
            provider="2gis",
            address_status="resolved",
            explanation=f"Точный адрес геокодирован через 2GIS",
        )

    # Nominatim fallback
    coords = await _geocode_nominatim(address_str)
    if coords:
        if db:
            await _save_cache(address_str, coords, "nominatim", db)
        return GeocodingResult(
            latitude=coords[0],
            longitude=coords[1],
            provider="nominatim",
            address_status="resolved",
            explanation=f"Точный адрес геокодирован через Nominatim (2GIS не нашёл)",
        )

    # Both failed → fall back to city center
    log.warning("  [GEO] full geocode failed → trying city center")
    return await _geocode_city_center(country, region, city, db,
        explanation=f"Точный адрес не найден — использован центр города {city}")


# ── Cache helpers ──

async def _check_cache(query: str, db: AsyncSession) -> GeocodingResult | None:
    result = await db.execute(
        select(GeocodingCache).where(GeocodingCache.address_query == query)
    )
    cached = result.scalar_one_or_none()
    if cached and cached.latitude and cached.longitude:
        return GeocodingResult(
            latitude=cached.latitude,
            longitude=cached.longitude,
            provider=cached.provider or "cache",
            address_status="resolved",
        )
    return None


async def _save_cache(
    query: str,
    coords: tuple[float, float],
    provider: str,
    db: AsyncSession,
):
    cache_entry = GeocodingCache(
        address_query=query,
        latitude=coords[0],
        longitude=coords[1],
        provider=provider,
    )
    db.add(cache_entry)
    try:
        await db.flush()
    except Exception:
        await db.rollback()


# ── Database integration ──

async def geocode_ticket(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> GeocodingResult:
    """Geocode a ticket's address and update DB."""
    proc = ProcessingState(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage=ProcessingStageEnum.geocoding,
        status=StageStatusEnum.in_progress,
        started_at=datetime.utcnow(),
    )
    db.add(proc)
    await db.flush()

    start_time = time.time()

    try:
        result = await geocode_address(
            country=ticket.country,
            region=ticket.region,
            city=ticket.city,
            street=ticket.street,
            house=ticket.house,
            db=db,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        ticket.latitude = result.latitude
        ticket.longitude = result.longitude
        ticket.address_status = result.address_status
        ticket.geo_explanation = result.explanation
        if result.latitude and result.longitude:
            ticket.geo_point = f"SRID=4326;POINT({result.longitude} {result.latitude})"

        proc.status = StageStatusEnum.completed
        proc.completed_at = datetime.utcnow()
        proc.progress_pct = 100.0
        proc.message = f"Geocoded via {result.provider} ({elapsed_ms}ms)"
        await db.flush()

        # SSE
        await sse_manager.send_update(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage="geocoding",
            status="completed",
            field="coordinates",
            data={
                "latitude": result.latitude,
                "longitude": result.longitude,
                "provider": result.provider,
                "address_status": result.address_status,
                "geo_explanation": result.explanation,
            },
        )

        return result

    except Exception as e:
        proc.status = StageStatusEnum.failed
        proc.completed_at = datetime.utcnow()
        proc.error_detail = str(e)
        await db.flush()

        await sse_manager.send_update(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage="geocoding",
            status="failed",
            message=str(e),
        )

        return GeocodingResult(address_status="unknown",
                              explanation=f"Ошибка геокодирования: {str(e)}")
