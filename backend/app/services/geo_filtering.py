import math
import csv
import os
import logging

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