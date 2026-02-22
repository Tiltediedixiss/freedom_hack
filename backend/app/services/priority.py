import math
from datetime import date, datetime
from collections import Counter

from app.core.config import get_settings

TYPE_PRIORITY_SCORE = {
    "Мошеннические действия": 10,
    "Претензия": 8,
    "Жалоба": 7,
    "Неработоспособность приложения": 6,
    "Смена данных": 5,
    "Консультация": 3,
    "Спам": 1,
}

SEGMENT_PRIORITY_SCORE = {
    "VIP": 10,
    "Priority": 7,
    "Mass": 3,
}

SENTIMENT_PRIORITY_SCORE = {
    "Негативный": 8,
    "Нейтральный": 4,
    "Позитивный": 2,
}

WEIGHTS = {
    "segment": 0.30,
    "type": 0.25,
    "sentiment": 0.15,
    "age": 0.10,
    "repeat_client": 0.07,
}

DEFAULT_SCORE = 4

AGE_BRACKETS = [
    (55, 10),
    (50, 8),
    (40, 6),
    (25, 4),
    (0, 3),
]

REPEAT_SCORES = [
    (4, 10),
    (3, 8),
    (2, 5),
    (1, 4),
]

FRAUD_SOFT_FLOOR = 8
FIFO_EXTRA = 1
EXPANSION_EXTRA = 1.0
YOUNG_VIP_EXTRA = 1.0
YOUNG_VIP_AGE_THRESHOLD = 30


def parse_birth_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None

    raw = str(raw).strip()
    if " " in raw:
        raw = raw[:raw.find(" ")].strip()
    today = date.today()

    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            if parsed > today:
                return date(today.year, 1, 1)
            return parsed
        except ValueError:
            continue

    parts = raw.replace("/", ".").replace("-", ".").split(".")
    year, month, day = None, None, 1

    for p in parts:
        p = p.strip()
        if not p.isdigit():
            continue
        num = int(p)
        if num > 1900 and year is None:
            year = num
        elif 1 <= num <= 12 and month is None:
            month = num
        elif 1 <= num <= 31 and day == 1:
            day = num

    if year is None:
        if len(parts) >= 3 and parts[2].strip().isdigit():
            candidate = int(parts[2].strip())
            if 1900 < candidate < 2100:
                year = candidate
        if year is None:
            return date(today.year, 1, 1)

    if month is None:
        month = 1

    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1

    try:
        result = date(year, month, day)
        if result > today:
            return date(today.year, 1, 1)
        return result
    except ValueError:
        return date(year, 1, 1)


def compute_age(birth_date: date | None) -> int | None:
    if not birth_date:
        return None
    today = date.today()
    age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return max(0, age)


def _age_score(age: int | None) -> float:
    if age is None:
        return DEFAULT_SCORE
    for threshold, score in AGE_BRACKETS:
        if age >= threshold:
            return score
    return DEFAULT_SCORE


def _repeat_score(guid_count: int) -> float:
    for threshold, score in REPEAT_SCORES:
        if guid_count >= threshold:
            return score
    return DEFAULT_SCORE


def _fifo_score(csv_row_index: int, total_rows: int) -> float:
    if total_rows <= 1:
        return FIFO_EXTRA
    return FIFO_EXTRA * (1.0 - csv_row_index / (total_rows - 1))


def build_repeat_counter(guids: list[str]) -> dict[str, int]:
    return dict(Counter(guids))


def compute_priority(
    segment: str,
    ticket_type: str,
    sentiment: str,
    age: int | None,
    country: str | None,
    csv_row_index: int,
    total_rows: int,
    guid_counts: dict[str, int],
    guid: str,
) -> dict:
    seg_raw = SEGMENT_PRIORITY_SCORE.get(segment, 3)
    type_raw = TYPE_PRIORITY_SCORE.get(ticket_type, 3)
    sent_raw = SENTIMENT_PRIORITY_SCORE.get(sentiment, 4)
    age_raw = _age_score(age)
    repeat_raw = _repeat_score(guid_counts.get(guid, 1))

    seg_w = seg_raw * WEIGHTS["segment"]
    type_w = type_raw * WEIGHTS["type"]
    sent_w = sent_raw * WEIGHTS["sentiment"]
    age_w = age_raw * WEIGHTS["age"]
    repeat_w = repeat_raw * WEIGHTS["repeat_client"]

    base_total = seg_w + type_w + sent_w + age_w + repeat_w

    settings = get_settings()
    extra_expansion = EXPANSION_EXTRA if (country and country.strip() in settings.EXPANSION_COUNTRIES) else 0.0
    extra_young_vip = YOUNG_VIP_EXTRA if (age is not None and age < YOUNG_VIP_AGE_THRESHOLD and segment == "VIP") else 0.0
    extra_fifo = _fifo_score(csv_row_index, total_rows)
    extra_total = extra_expansion + extra_young_vip + extra_fifo

    fraud_floor_applied = False
    final = base_total + extra_total
    if ticket_type == "Мошеннические действия" and final < FRAUD_SOFT_FLOOR:
        final = FRAUD_SOFT_FLOOR
        fraud_floor_applied = True

    final = min(10.0, max(1.0, round(final, 2)))

    return {
        "segment": round(seg_w, 3),
        "type": round(type_w, 3),
        "sentiment": round(sent_w, 3),
        "age": round(age_w, 3),
        "repeat_client": round(repeat_w, 3),
        "base_total": round(base_total, 2),
        "extra_expansion": extra_expansion,
        "extra_young_vip": extra_young_vip,
        "extra_fifo": round(extra_fifo, 3),
        "extra_total": round(extra_total, 3),
        "fraud_floor_applied": fraud_floor_applied,
        "final": final,
    }


def score_batch(tickets: list[dict]) -> list[dict]:
    guids = [t["guid"] for t in tickets]
    guid_counts = build_repeat_counter(guids)
    total_rows = len(tickets)

    results = []
    for t in tickets:
        if t.get("is_spam") and t.get("priority_breakdown"):
            results.append({
                "csv_row_index": t["csv_row_index"],
                "priority": t["priority_breakdown"],
            })
            continue

        ticket_type = t.get("type") or "Консультация"
        sentiment = t.get("sentiment") or "Нейтральный"

        priority = compute_priority(
            segment=t["segment"],
            ticket_type=ticket_type,
            sentiment=sentiment,
            age=t.get("age"),
            country=t.get("country"),
            csv_row_index=t["csv_row_index"],
            total_rows=total_rows,
            guid_counts=guid_counts,
            guid=t["guid"],
        )

        results.append({
            "csv_row_index": t["csv_row_index"],
            "priority": priority,
        })

    return results