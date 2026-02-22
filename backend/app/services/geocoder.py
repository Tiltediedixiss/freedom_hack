"""
Step 5: Idnetifying Coordinates from Adresses

Processes the potentially "dirty" data for addresses to either:
- Idnetify the Coordinates
- Or assign as Unkown

"""

import logging

import random
import time

import httpx

from app.core.config import get_settings

log = logging.getLogger("fire.geocoder")

CAPITAL_COORDS = {
    "казахстан": (51.1694, 71.4491),
    "kazakhstan": (51.1694, 71.4491),
    "россия": (55.7558, 37.6173),
    "russia": (55.7558, 37.6173),
    "узбекистан": (41.2995, 69.2401),
    "uzbekistan": (41.2995, 69.2401),
    "украина": (50.4501, 30.5234),
    "ukraine": (50.4501, 30.5234),
    "азербайджан": (40.4093, 49.8671),
    "azerbaijan": (40.4093, 49.8671),
    "кыргызстан": (42.8746, 74.5698),
    "kyrgyzstan": (42.8746, 74.5698),
    "таджикистан": (38.5598, 68.7738),
    "tajikistan": (38.5598, 68.7738),
    "туркменистан": (37.9601, 58.3261),
    "turkmenistan": (37.9601, 58.3261),
    "беларусь": (53.9006, 27.5590),
    "belarus": (53.9006, 27.5590),
    "молдова": (47.0105, 28.8638),
    "moldova": (47.0105, 28.8638),
    "грузия": (41.7151, 44.8271),
    "georgia": (41.7151, 44.8271),
    "армения": (40.1872, 44.5152),
    "armenia": (40.1872, 44.5152),
}

CIS_COUNTRIES = [
    "Казахстан", "Россия", "Узбекистан", "Украина",
    "Кыргызстан", "Таджикистан", "Беларусь", "Молдова",
    "Грузия", "Армения", "Азербайджан", "Туркменистан",
]

ASTANA_COORDS = (51.1694, 71.4491)
ALMATY_COORDS = (43.2220, 76.8512)

_KZ_NAMES = {"казахстан", "kazakhstan", "кз", "kz"}

_cache: dict[str, tuple[float, float]] = {}
_unknown_counter = 0


def _is_kazakhstan(country: str) -> bool:
    return country.strip().lower() in _KZ_NAMES


def _clean_city(city: str) -> str:
    c = city.strip()
    if "/" in c:
        c = c.split("/")[0].strip()
    if "(" in c:
        c = c.split("(")[0].strip()
    return c


def _build_query(*parts: str | None) -> str:
    return ", ".join(p.strip() for p in parts if p and p.strip())


async def _geocode_2gis(address: str) -> tuple[float, float] | None:
    settings = get_settings()
    if not settings.TWOGIS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://catalog.api.2gis.com/3.0/items/geocode",
                params={"q": address, "fields": "items.point", "key": settings.TWOGIS_API_KEY},
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
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "FIRE-Geocoder/1.0"},
            )
            response.raise_for_status()
            data = response.json()
        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        pass
    return None


async def _geocode(query: str) -> tuple[tuple[float, float] | None, str]:
    if query in _cache:
        return _cache[query], "cache"

    coords = await _geocode_2gis(query)
    if coords:
        _cache[query] = coords
        return coords, "2gis"

    coords = await _geocode_nominatim(query)
    if coords:
        _cache[query] = coords
        return coords, "nominatim"

    return None, "failed"


async def _geocode_city_center(country: str, region: str | None, city: str) -> tuple[tuple[float, float] | None, str, str]:
    clean = _clean_city(city)
    query = _build_query(country, region, clean)
    coords, provider = await _geocode(query)
    if coords:
        return coords, f"{provider}_city", f"Использован центр города {clean}"

    query_simple = _build_query(country, clean)
    coords, provider = await _geocode(query_simple)
    if coords:
        return coords, f"{provider}_city", f"Использован центр города {clean} (без области)"

    global _unknown_counter
    _unknown_counter += 1
    fallback = ASTANA_COORDS if _unknown_counter % 2 == 0 else ALMATY_COORDS
    city_name = "Астана" if _unknown_counter % 2 == 0 else "Алматы"
    return fallback, "city_fallback", f"Город {clean} не найден — назначен офис {city_name}"


async def _search_city_in_cis(city: str) -> tuple[tuple[float, float] | None, str, str]:
    clean = _clean_city(city)
    shuffled = CIS_COUNTRIES.copy()
    random.shuffle(shuffled)

    for cis_country in shuffled:
        query = f"{clean}, {cis_country}"
        coords, provider = await _geocode(query)
        if coords:
            return coords, f"{provider}_cis", f"Страна не указана — город {clean} найден в {cis_country}"

    return None, "cis_failed", f"Город {clean} не найден в странах СНГ"


async def geocode_ticket(ticket: dict) -> dict:
    start = time.time()

    country = (ticket.get("country") or "").strip() or None
    region = (ticket.get("region") or "").strip() or None
    city = (ticket.get("city") or "").strip() or None
    street = (ticket.get("street") or "").strip() or None
    house = (ticket.get("house") or "").strip() or None

    coords = None
    provider = "none"
    explanation = ""

    if not country:
        if city:
            coords, provider, explanation = await _search_city_in_cis(city)
        else:
            explanation = "Координаты не определены: страна и город не указаны"
    elif not _is_kazakhstan(country):
        global _unknown_counter
        _unknown_counter += 1
        coords = ASTANA_COORDS if _unknown_counter % 2 == 0 else ALMATY_COORDS
        city_name = "Астана" if _unknown_counter % 2 == 0 else "Алматы"
        provider = "international_5050"
        explanation = f"Иностранный адрес ({country}) — маршрутизация в офис {city_name}"
    elif not city:
        coords = CAPITAL_COORDS.get(country.lower(), ASTANA_COORDS)
        provider = "capital_fallback"
        explanation = "Город не указан — координаты столицы (Астана)"
    elif not street:
        coords, provider, explanation = await _geocode_city_center(country, region, city)
    elif not house:
        coords, provider, explanation = await _geocode_city_center(country, region, city)
        explanation = f"Дом не указан — {explanation.lower()}"
    else:
        clean_city = _clean_city(city)
        query = _build_query(country, region, clean_city, street, house)
        coords, provider = await _geocode(query)
        if coords:
            explanation = f"Точный адрес геокодирован через {provider}"
        else:
            coords, provider, explanation = await _geocode_city_center(country, region, city)
            explanation = f"Точный адрес не найден — {explanation.lower()}"

    elapsed = time.time() - start

    ticket["latitude"] = coords[0] if coords else None
    ticket["longitude"] = coords[1] if coords else None
    ticket["geo_provider"] = provider
    ticket["geo_explanation"] = explanation
    ticket["geo_latency_ms"] = int(elapsed * 1000)

    return ticket


async def geocode_batch(tickets: list[dict], concurrency: int = 10) -> list[dict]:
    import asyncio
    sem = asyncio.Semaphore(concurrency)

    async def _process(t: dict) -> dict:
        if t.get("is_spam"):
            t["latitude"] = None
            t["longitude"] = None
            t["geo_provider"] = "skipped"
            t["geo_explanation"] = "Спам — геокодирование пропущено"
            t["geo_latency_ms"] = 0
            return t
        async with sem:
            return await geocode_ticket(t)

    return list(await asyncio.gather(*[_process(t) for t in tickets]))