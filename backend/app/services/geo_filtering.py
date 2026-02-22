import math
import csv
import os
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Assignment, BusinessUnit, Manager, Ticket

log = logging.getLogger("pipeline.geo_filter")

OFFICE_COORDS: dict[str, tuple[float, float]] = {}

KNOWN_CITY_COORDS = {
    "Актау": (43.6353, 51.1480),
    "Актобе": (50.2839, 57.1670),
    "Алматы": (43.2220, 76.8512),
    "Астана": (51.1694, 71.4491),
    "Атырау": (47.1065, 51.9203),
    "Караганда": (49.8048, 73.1094),
    "Кокшетау": (53.2833, 69.3833),
    "Костанай": (53.2198, 63.6354),
    "Кызылорда": (44.8479, 65.5022),
    "Павлодар": (52.2873, 76.9674),
    "Петропавловск": (54.8753, 69.1629),
    "Тараз": (42.9000, 71.3667),
    "Уральск": (51.2333, 51.3667),
    "Усть-Каменогорск": (49.9483, 82.6278),
    "Шымкент": (42.3167, 69.5950),
}

EARTH_RADIUS_KM = 6371.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def load_office_coords(business_units_csv_path: str | None = None):
    global OFFICE_COORDS
    OFFICE_COORDS = dict(KNOWN_CITY_COORDS)

    if business_units_csv_path and os.path.exists(business_units_csv_path):
        try:
            with open(business_units_csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city = None
                    for key in row:
                        if key and key.strip() and key.strip() != "Адрес":
                            city = row[key] if row[key] and row[key].strip() else key.strip()
                            break
                    if city and city.strip() and city.strip() in KNOWN_CITY_COORDS:
                        OFFICE_COORDS[city.strip()] = KNOWN_CITY_COORDS[city.strip()]
        except Exception as e:
            log.warning("Failed to load business_units CSV: %s", e)

    log.info("Loaded %d office coordinates", len(OFFICE_COORDS))


def get_office_coords(office_name: str) -> tuple[float, float] | None:
    if not OFFICE_COORDS:
        load_office_coords()
    return OFFICE_COORDS.get(office_name.strip())


def filter_by_geo(ticket: dict, managers: list[dict]) -> list[dict]:
    ticket_lat = ticket.get("latitude")
    ticket_lon = ticket.get("longitude")

    if ticket_lat is None or ticket_lon is None:
        ticket["_geo_filter_note"] = "Координаты тикета отсутствуют — гео-фильтрация пропущена"
        return managers

    distances = []
    for m in managers:
        office = m.get("office", "").strip()
        coords = get_office_coords(office)
        if coords is None:
            continue
        dist = _haversine(ticket_lat, ticket_lon, coords[0], coords[1])
        distances.append((m, dist))

    if not distances:
        ticket["_geo_filter_note"] = "Координаты офисов не найдены — гео-фильтрация пропущена"
        return managers

    distances.sort(key=lambda x: x[1])
    min_dist = distances[0][1]
    max_allowed = min_dist * 1.5

    if max_allowed < 50:
        max_allowed = 50

    eligible = [m for m, d in distances if d <= max_allowed]

    for m, d in distances:
        m["_geo_distance_km"] = round(d, 1)

    ticket["_geo_filter_note"] = (
        f"Ближайший офис: {distances[0][0].get('office')} ({min_dist:.0f} км). "
        f"Порог: {max_allowed:.0f} км. "
        f"Прошли: {len(eligible)}/{len(distances)} менеджеров."
    )

    return eligible


@dataclass
class ManagerCandidate:
    """Single candidate for routing: manager, their office, and distance to ticket."""
    manager: Manager
    business_unit: Optional[BusinessUnit]
    distance_km: float
    office_name: Optional[str]


async def get_candidate_managers(
    ticket: Ticket,
    db: AsyncSession,
    max_km: float = 500.0,
) -> list[ManagerCandidate]:
    """
    Load active managers with business units, compute distance from ticket coords,
    filter by max_km, return sorted by distance (nearest first).
    """
    if ticket.latitude is None or ticket.longitude is None:
        return []

    result = await db.execute(
        select(Manager)
        .where(Manager.is_active == True)
        .options(selectinload(Manager.business_unit))
    )
    managers = list(result.scalars().all())
    candidates: list[ManagerCandidate] = []

    for m in managers:
        bu = m.business_unit
        if bu is None or bu.latitude is None or bu.longitude is None:
            continue
        dist = _haversine(
            float(ticket.latitude), float(ticket.longitude),
            float(bu.latitude), float(bu.longitude),
        )
        if dist <= max_km:
            candidates.append(ManagerCandidate(
                manager=m,
                business_unit=bu,
                distance_km=round(dist, 1),
                office_name=bu.name,
            ))

    candidates.sort(key=lambda c: c.distance_km)
    return candidates


async def assign_ticket_to_nearest(
    ticket: Ticket,
    db: AsyncSession,
    batch_id: Optional[str] = None,
) -> Optional[Assignment]:
    """
    Find nearest manager by office coords, create Assignment, set ticket.assigned_manager_id.
    """
    candidates = await get_candidate_managers(ticket, db, max_km=500.0)
    if not candidates:
        return None

    nearest = candidates[0]
    assignment = Assignment(
        ticket_id=ticket.id,
        manager_id=nearest.manager.id,
        business_unit_id=nearest.business_unit.id if nearest.business_unit else None,
        explanation="Ближайший офис по координатам тикета",
        routing_details={
            "distance_km": nearest.distance_km,
            "office_name": nearest.office_name or (nearest.business_unit.name if nearest.business_unit else None),
        },
    )
    db.add(assignment)
    ticket.assigned_manager_id = nearest.manager.id
    return assignment