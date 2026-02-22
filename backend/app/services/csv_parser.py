"""
Step 1: 3 csv parsing - managers.csv, business_units.csv, and tickets.csv.
Async ingest_* functions for API: parse from bytes and insert into DB.
"""
import io
import re
import csv
import logging
import uuid
from datetime import datetime, date
from collections import Counter
from typing import Any

import chardet
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    BatchUpload,
    BusinessUnit,
    Manager,
    Ticket,
    ManagerPositionEnum,
    SegmentEnum,
    TicketStatusEnum,
    SEGMENT_MAP as MODEL_SEGMENT_MAP,
)

log = logging.getLogger("fire.csv_parser")

POSITION_MAP = {
    "специалист": "Специалист",
    "ведущий специалист": "Ведущий специалист",
    "главный специалист": "Главный специалист",
}

COUNTRY_NORMALIZE = {
    "kazakhstan": "Казахстан",
    "кз": "Казахстан",
    "kz": "Казахстан",
}


def _read_csv(path: str) -> pd.DataFrame:
    with open(path, "rb") as f:
        raw = f.read()
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    text = raw.decode(enc, errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def _read_csv_from_bytes(contents: bytes) -> pd.DataFrame:
    enc = chardet.detect(contents).get("encoding") or "utf-8"
    text = contents.decode(enc, errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def _clean(value: Any) -> str | None:
    if pd.isna(value) or value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _safe_int(value: Any) -> int:
    if pd.isna(value) or value is None:
        return 0
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 0


def _parse_date(value: Any) -> date | None:
    s = _clean(value)
    if not s:
        return None

    today = date.today()

    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d.%m.%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y"]:
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year > today.year:
                return date(today.year, d.month, d.day)
            return d
        except ValueError:
            continue

    try:
        d = pd.to_datetime(s, dayfirst=False).date()
        if d.year > today.year:
            return date(today.year, 1, 1)
        return d
    except Exception:
        return None


def _compute_age(birth_date: date | None) -> int | None:
    if not birth_date:
        return None
    today = date.today()
    age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return max(0, age)


def _normalize_country(value: Any) -> str | None:
    s = _clean(value)
    if not s:
        return None
    key = s.strip().lower()
    return COUNTRY_NORMALIZE.get(key, s)


def _parse_skills(value: Any) -> list[str]:
    s = _clean(value)
    if not s:
        return []
    return [sk.strip().upper() for sk in s.split(",") if sk.strip()]


def _parse_position(value: Any) -> str:
    s = _clean(value)
    if not s:
        return "Специалист"
    return POSITION_MAP.get(s.strip().lower(), "Специалист")


def _parse_attachments(value: Any) -> str | None:
    s = _clean(value)
    if not s:
        return None
    return s


# ────────────────────────────────────────────────────────────
# PUBLIC API
# ────────────────────────────────────────────────────────────

def parse_business_units(path: str | None = None, data: bytes | None = None) -> list[dict]:
    if data is not None:
        df = _read_csv_from_bytes(data)
    elif path:
        df = _read_csv(path)
    else:
        raise ValueError("Either path or data must be provided")

    col_map = {}
    for col in df.columns:
        c = col.lower()
        if "офис" in c or "office" in c or col == df.columns[0]:
            col_map[col] = "office"
        elif "адрес" in c or "address" in c:
            col_map[col] = "address"
    df = df.rename(columns=col_map)

    units = []
    for _, row in df.iterrows():
        office = _clean(row.get("office"))
        if not office:
            continue
        units.append({
            "office": office,
            "address": _clean(row.get("address")),
        })

    log.info("Parsed %d business units", len(units))
    return units


def parse_managers(path: str | None = None, data: bytes | None = None) -> list[dict]:
    if data is not None:
        df = _read_csv_from_bytes(data)
    elif path:
        df = _read_csv(path)
    else:
        raise ValueError("Either path or data must be provided")

    col_map = {}
    for col in df.columns:
        c = col.lower()
        if "фио" in c or "имя" in c or "name" in c:
            col_map[col] = "full_name"
        elif "должность" in c or "position" in c:
            col_map[col] = "position"
        elif "офис" in c or "office" in c:
            col_map[col] = "office"
        elif "навык" in c or "skill" in c:
            col_map[col] = "skills"
        elif "количество" in c or "обращен" in c or "load" in c:
            col_map[col] = "csv_load"
    df = df.rename(columns=col_map)

    managers = []
    for idx, row in df.iterrows():
        full_name = _clean(row.get("full_name"))
        if not full_name:
            continue

        position = _parse_position(row.get("position"))
        skills = _parse_skills(row.get("skills"))
        csv_load = _safe_int(row.get("csv_load"))

        managers.append({
            "id": idx + 1,
            "full_name": full_name,
            "position": position,
            "office": _clean(row.get("office")) or "",
            "skills": skills,
            "csv_load": csv_load,
        })

    log.info("Parsed %d managers", len(managers))
    return managers


def parse_tickets(path: str | None = None, data: bytes | None = None) -> list[dict]:
    if data is not None:
        df = _read_csv_from_bytes(data)
    elif path:
        df = _read_csv(path)
    else:
        raise ValueError("Either path or data must be provided")

    col_map = {}
    for col in df.columns:
        c = col.lower()
        if "guid" in c:
            col_map[col] = "guid"
        elif "пол" in c or "gender" in c:
            col_map[col] = "gender"
        elif "рождени" in c or "birth" in c or "дата" in c:
            col_map[col] = "birth_date"
        elif "описание" in c or "description" in c:
            col_map[col] = "description"
        elif "вложени" in c or "attach" in c:
            col_map[col] = "attachments"
        elif "сегмент" in c or "segment" in c:
            col_map[col] = "segment"
        elif "страна" in c or "country" in c:
            col_map[col] = "country"
        elif "область" in c or "region" in c:
            col_map[col] = "region"
        elif "населённый" in c or "населенный" in c or "город" in c or "city" in c:
            col_map[col] = "city"
        elif "улица" in c or "street" in c:
            col_map[col] = "street"
        elif "дом" in c or "house" in c:
            col_map[col] = "house"
    df = df.rename(columns=col_map)

    guid_series = df.get("guid")
    guid_counts = {}
    if guid_series is not None:
        guid_counts = dict(Counter(guid_series.str.strip()))

    tickets = []
    for idx, row in df.iterrows():
        guid = _clean(row.get("guid"))
        birth_date = _parse_date(row.get("birth_date"))
        age = _compute_age(birth_date)
        description = _clean(row.get("description"))
        attachments = _parse_attachments(row.get("attachments"))
        country = _normalize_country(row.get("country"))
        segment = _clean(row.get("segment")) or "Mass"

        tickets.append({
            "ticket_id": idx + 1,
            "csv_row_index": idx,
            "guid": guid,
            "gender": _clean(row.get("gender")),
            "birth_date": str(birth_date) if birth_date else None,
            "age": age,
            "description": description,
            "attachments": attachments,
            "segment": segment,
            "country": country,
            "region": _clean(row.get("region")),
            "city": _clean(row.get("city")),
            "street": _clean(row.get("street")),
            "house": _clean(row.get("house")),
            "guid_count": guid_counts.get(guid, 0) if guid else 0,

            # Filled by later stages (None = not yet processed)
            "is_spam": None,
            "spam_probability": None,
            "spam_reason": None,
            "type": None,
            "language_label": None,
            "sentiment": None,
            "sentiment_confidence": None,
            "summary": None,
            "latitude": None,
            "longitude": None,
            "priority": None,
            "priority_breakdown": None,
            "assigned_manager_id": None,
            "assigned_manager_name": None,
            "assigned_office": None,
            "routing_explanation": None,
        })

    log.info("Parsed %d tickets", len(tickets))
    return tickets


# ────────────────────────────────────────────────────────────
# ASYNC INGEST (API: bytes + DB)
# ────────────────────────────────────────────────────────────

async def ingest_business_units_csv(
    db: AsyncSession,
    contents: bytes,
    filename: str,
) -> dict:
    """Parse business_units CSV from bytes and insert into DB. Returns {total_imported, errors}."""
    errors: list[str] = []
    units = parse_business_units(data=contents)
    total = 0
    for u in units:
        try:
            name = (u.get("office") or "").strip()
            if not name:
                continue
            existing = await db.execute(select(BusinessUnit).where(BusinessUnit.name == name))
            if existing.scalar_one_or_none():
                continue
            bu = BusinessUnit(name=name, address=_clean(u.get("address")))
            db.add(bu)
            total += 1
        except Exception as e:
            errors.append(f"{name or '?'}: {e}")
    await db.flush()
    return {"total_imported": total, "errors": errors}


async def ingest_managers_csv(
    db: AsyncSession,
    contents: bytes,
    filename: str,
) -> dict:
    """Parse managers CSV from bytes and insert into DB. Returns {total_imported, errors}."""
    errors: list[str] = []
    # Ensure business units exist for office name lookup
    result = await db.execute(select(BusinessUnit))
    bu_by_name = {bu.name: bu.id for bu in result.scalars().all()}
    managers = parse_managers(data=contents)
    total = 0
    for m in managers:
        try:
            full_name = (m.get("full_name") or "").strip()
            if not full_name:
                continue
            pos_str = (m.get("position") or "Специалист").strip().lower().replace(" ", "_")
            position = getattr(ManagerPositionEnum, pos_str, ManagerPositionEnum.специалист)
            office = (m.get("office") or "").strip()
            bu_id = bu_by_name.get(office)
            skills = m.get("skills") or []
            if isinstance(skills, str):
                skills = _parse_skills(skills)
            man = Manager(
                full_name=full_name,
                position=position,
                business_unit_id=bu_id,
                skills=skills,
                csv_load=_safe_int(m.get("csv_load")),
            )
            db.add(man)
            total += 1
        except Exception as e:
            errors.append(f"{m.get('full_name', '?')}: {e}")
    await db.flush()
    return {"total_imported": total, "errors": errors}


def _segment_to_enum(segment: Any) -> SegmentEnum:
    s = _clean(segment) or "mass"
    key = s.lower().replace(" ", "")
    return MODEL_SEGMENT_MAP.get(key, MODEL_SEGMENT_MAP.get("mass", SegmentEnum.Mass))


async def ingest_tickets_csv(
    db: AsyncSession,
    contents: bytes,
    filename: str,
) -> dict:
    """Parse tickets CSV from bytes, insert into DB, create BatchUpload. Returns batch_id, total_rows, processed_rows, failed_rows, errors."""
    errors: list[str] = []
    tickets_data = parse_tickets(data=contents)
    batch = BatchUpload(
        filename=filename,
        total_rows=len(tickets_data),
        processed_rows=0,
        failed_rows=0,
        status="pending",
        error_log=[],
    )
    db.add(batch)
    await db.flush()
    processed = 0
    failed = 0
    for row in tickets_data:
        try:
            birth_date = None
            if row.get("birth_date"):
                birth_date = _parse_date(row["birth_date"])
            segment = _segment_to_enum(row.get("segment"))
            attachments = row.get("attachments")
            if isinstance(attachments, str) and attachments:
                attachments = [a.strip() for a in attachments.split(",") if a.strip()]
            else:
                attachments = attachments or []
            ticket = Ticket(
                csv_row_index=row.get("csv_row_index"),
                guid=_clean(row.get("guid")),
                gender=_clean(row.get("gender")),
                birth_date=birth_date,
                age=row.get("age"),
                description=_clean(row.get("description")),
                attachments=attachments,
                segment=segment,
                country=_clean(row.get("country")),
                region=_clean(row.get("region")),
                city=_clean(row.get("city")),
                street=_clean(row.get("street")),
                house=_clean(row.get("house")),
                status=TicketStatusEnum.ingested,
                id_count_of_user=row.get("guid_count") or 0,
            )
            db.add(ticket)
            processed += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {row.get('csv_row_index', '?')}: {e}")
    batch.processed_rows = processed
    batch.failed_rows = failed
    batch.status = "completed"
    batch.error_log = errors
    await db.flush()
    return {
        "batch_id": str(batch.id),
        "total_rows": len(tickets_data),
        "processed_rows": processed,
        "failed_rows": failed,
        "errors": errors,
    }


if __name__ == "__main__":
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    base = sys.argv[1] if len(sys.argv) > 1 else "."

    bu = parse_business_units(f"{base}/business_units.csv")
    mgrs = parse_managers(f"{base}/managers.csv")
    tix = parse_tickets(f"{base}/tickets.csv")

    print(f"\n{'='*70}")
    print(f"  BUSINESS UNITS: {len(bu)}")
    print(f"{'='*70}")
    for b in bu:
        print(f"  {b['office']:<20} {(b['address'] or '')[:50]}")

    print(f"\n{'='*70}")
    print(f"  MANAGERS: {len(mgrs)}")
    print(f"{'='*70}")
    print(f"  {'Name':<15} {'Position':<25} {'Office':<18} {'Skills':<15} {'Load'}")
    print(f"  {'─'*15} {'─'*25} {'─'*18} {'─'*15} {'─'*4}")
    for m in mgrs:
        print(f"  {m['full_name']:<15} {m['position']:<25} {m['office']:<18} {','.join(m['skills']):<15} {m['csv_load']}")

    positions = Counter(m["position"] for m in mgrs)
    offices = Counter(m["office"] for m in mgrs)
    print(f"\n  Position breakdown: {dict(positions)}")
    print(f"  Managers per office: {dict(offices)}")

    skills_dist = Counter()
    for m in mgrs:
        for s in m["skills"]:
            skills_dist[s] += 1
    print(f"  Skill distribution: {dict(skills_dist)}")

    print(f"\n{'='*70}")
    print(f"  TICKETS: {len(tix)}")
    print(f"{'='*70}")

    segments = Counter(t["segment"] for t in tix)
    countries = Counter(t["country"] for t in tix)
    age_dist = {"<25": 0, "25-39": 0, "40-54": 0, "55+": 0, "unknown": 0}
    for t in tix:
        a = t["age"]
        if a is None:
            age_dist["unknown"] += 1
        elif a < 25:
            age_dist["<25"] += 1
        elif a < 40:
            age_dist["25-39"] += 1
        elif a < 55:
            age_dist["40-54"] += 1
        else:
            age_dist["55+"] += 1

    empty_desc = sum(1 for t in tix if not t["description"])
    has_attach = sum(1 for t in tix if t["attachments"])
    unique_cities = len(set(t["city"] for t in tix if t["city"]))

    print(f"  Segments:      {dict(segments)}")
    print(f"  Countries:     {dict(countries)}")
    print(f"  Age brackets:  {age_dist}")
    print(f"  Empty descriptions: {empty_desc}")
    print(f"  With attachments:   {has_attach}")
    print(f"  Unique cities:      {unique_cities}")
    print(f"  GUID repeats:       {sum(1 for t in tix if t['guid_count'] > 1)}")

    print(f"\n  Sample tickets (first 3):")
    for t in tix[:3]:
        desc = (t["description"] or "")[:80]
        print(f"    Row {t['csv_row_index']}: {t['segment']:<10} age={str(t['age']):<4} {t['city'] or '?':<20} \"{desc}...\"")