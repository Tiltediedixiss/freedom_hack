"""
T2 — CSV Parser & Data Ingestion Service.

Handles:
  • tickets.csv: Russian headers → DB columns, age computation, feature engineering
  • managers.csv: position → skill_factor mapping, office linking
  • business_units.csv: office name + address
"""

import io
import re
import uuid
import math
from datetime import datetime, date
from typing import Any

import chardet
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sse_manager import sse_manager
from app.models.models import (
    BatchUpload, BusinessUnit, Manager, ProcessingState,
    ProcessingStageEnum, StageStatusEnum, Ticket, TicketStatusEnum,
    SegmentEnum, ManagerPositionEnum, POSITION_MAP, SEGMENT_MAP,
    POSITION_SKILL_FACTOR,
)
from app.services.geocoder import geocode_office_address


def _detect_encoding(raw_bytes: bytes) -> str:
    """Detect file encoding via chardet, fallback utf-8."""
    result = chardet.detect(raw_bytes)
    return result.get("encoding") or "utf-8"


def _clean_str(value: Any) -> str | None:
    """Convert to stripped string, or None if empty/NaN."""
    if pd.isna(value) or value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _safe_int(value: Any) -> int | None:
    if pd.isna(value) or value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_birth_date(value: Any) -> date | None:
    """
    Parse birth date from various formats with robust edge-case handling.

    Edge cases:
      • Invalid day (e.g. 31.02.1990)  → 1st of that month (01.02.1990)
      • Invalid/missing month           → January 1st of that year
      • Missing/future year (e.g. 2030) → use current year → age 0
    """
    if pd.isna(value) or value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Try standard formats first (happy path)
    for fmt in ["%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S %p",
                "%m/%d/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return _validate_birth_year(datetime.strptime(s, fmt).date())
        except ValueError:
            continue

    # Fallback: try pandas
    try:
        return _validate_birth_year(pd.to_datetime(s, dayfirst=False).date())
    except Exception:
        pass

    # Final fallback: extract numbers and handle invalid components
    return _parse_birth_date_manual(s)


def _validate_birth_year(d: date) -> date:
    """If year is in the future or clearly invalid, replace with current year."""
    today = date.today()
    if d.year > today.year:
        return date(today.year, d.month, d.day)
    return d


def _parse_birth_date_manual(s: str) -> date | None:
    """
    Manually parse a date string with invalid components.
    Handles cases like '42/1/1990', '1/50/1990', '12/31/2099'.
    """
    import calendar

    today = date.today()

    # Extract numbers from the string
    # Try to match M/D/Y pattern (with optional time suffix)
    m = re.match(
        r'(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{4})',
        s.split()[0] if ' ' in s else s,
    )
    if not m:
        return None

    part1, part2, year = int(m.group(1)), int(m.group(2)), int(m.group(3))

    # Clamp future year to current year
    if year > today.year:
        year = today.year

    # Determine month/day — assume M/D/Y format (US style matching CSV)
    month = part1
    day = part2

    # Invalid month → January 1st
    if month < 1 or month > 12:
        return date(year, 1, 1)

    # Invalid day → 1st of that month
    max_day = calendar.monthrange(year, month)[1]
    if day < 1 or day > max_day:
        return date(year, month, 1)

    return date(year, month, day)


def _compute_age(birth_date: date | None) -> int:
    """Compute age from birth date. Returns 0 if no birth date or future date."""
    if birth_date is None:
        return 0
    today = date.today()
    age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    # Future dates → treat as age 0
    return max(0, age)


def _parse_segment(value: Any) -> SegmentEnum | None:
    """Map CSV segment to enum."""
    s = _clean_str(value)
    if s is None:
        return None
    return SEGMENT_MAP.get(s.lower(), SegmentEnum.Mass)


def _parse_attachments(value: Any) -> list[str]:
    """Parse attachment field — can be comma/semicolon separated filenames."""
    s = _clean_str(value)
    if not s:
        return []
    for sep in [";", "|", ","]:
        if sep in s:
            return [a.strip() for a in s.split(sep) if a.strip()]
    return [s]


def _parse_position(value: Any) -> ManagerPositionEnum:
    """Map CSV position string to enum."""
    s = _clean_str(value)
    if s is None:
        return ManagerPositionEnum.специалист
    s_lower = s.lower().strip()
    return POSITION_MAP.get(s_lower, ManagerPositionEnum.специалист)


def _parse_skills(value: Any) -> list[str]:
    """Parse skills like 'VIP, ENG, KZ'."""
    s = _clean_str(value)
    if not s:
        return []
    return [sk.strip().upper() for sk in s.split(",") if sk.strip()]


# ═══════════════════════════════════════════════════════════════
# BUSINESS UNITS INGESTION
# ═══════════════════════════════════════════════════════════════

async def ingest_business_units_csv(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
) -> dict:
    """Parse business_units.csv: headers [Офис, Адрес]."""
    encoding = _detect_encoding(file_bytes)
    text = file_bytes.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

    # Normalize column names (Офис, Адрес, optional Страна/country)
    col_map = {}
    for col in df.columns:
        c = col.strip().lower()
        if "офис" in c or "office" in c or "name" in c:
            col_map[col] = "name"
        elif "адрес" in c or "address" in c:
            col_map[col] = "address"
        elif "страна" in c or "country" in c:
            col_map[col] = "country"
    df = df.rename(columns=col_map)

    imported = 0
    for _, row in df.iterrows():
        name = _clean_str(row.get("name"))
        if not name:
            continue

        # Upsert by name
        result = await db.execute(
            select(BusinessUnit).where(BusinessUnit.name == name)
        )
        existing = result.scalar_one_or_none()

        address = _clean_str(row.get("address"))
        country = _clean_str(row.get("country"))  # optional: Страна / country

        if existing:
            existing.address = address or existing.address
            bu = existing
        else:
            bu = BusinessUnit(name=name, address=address)
            db.add(bu)
            await db.flush()

        # Geocode office address so we have lat/lon for distance-based routing
        try:
            geo = await geocode_office_address(
                office_name=name, address=address, country=country, db=db
            )
            if geo.latitude is not None and geo.longitude is not None:
                bu.latitude = geo.latitude
                bu.longitude = geo.longitude
                bu.geo_point = f"SRID=4326;POINT({geo.longitude} {geo.latitude})"
        except Exception:
            pass  # leave lat/lon null if geocoding fails

        imported += 1

    await db.flush()
    return {"total_imported": imported, "filename": filename}


# ═══════════════════════════════════════════════════════════════
# MANAGERS INGESTION
# ═══════════════════════════════════════════════════════════════

async def ingest_managers_csv(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
) -> dict:
    """
    Parse managers.csv.
    Headers: ФИО, Должность, Офис, Навыки, Количество обращений в работе
    """
    encoding = _detect_encoding(file_bytes)
    text = file_bytes.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

    # Column mapping
    col_map = {}
    for col in df.columns:
        c = col.strip().lower()
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

    imported = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            full_name = _clean_str(row.get("full_name"))
            if not full_name:
                errors.append({"row": int(idx) + 2, "error": "Empty name"})
                continue

            position = _parse_position(row.get("position"))
            skill_factor = POSITION_SKILL_FACTOR.get(position, 1.0)
            skills = _parse_skills(row.get("skills"))
            csv_load = _safe_int(row.get("csv_load")) or 0

            # Link to business unit by office name
            office_name = _clean_str(row.get("office"))
            bu_id = None
            if office_name:
                result = await db.execute(
                    select(BusinessUnit).where(BusinessUnit.name == office_name)
                )
                bu = result.scalar_one_or_none()
                if bu:
                    bu_id = bu.id

            # Compute initial stress from existing load
            stress = csv_load * 2.5 / skill_factor

            manager = Manager(
                full_name=full_name,
                position=position,
                skill_factor=skill_factor,
                skills=skills,
                business_unit_id=bu_id,
                csv_load=csv_load,
                stress_score=stress,
            )
            db.add(manager)
            imported += 1

        except Exception as e:
            errors.append({"row": int(idx) + 2, "error": str(e)})

    await db.flush()
    return {"total_imported": imported, "errors": errors, "filename": filename}


# ═══════════════════════════════════════════════════════════════
# TICKETS INGESTION
# ═══════════════════════════════════════════════════════════════

async def ingest_tickets_csv(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
) -> dict:
    """
    Parse tickets.csv.
    Headers: GUID клиента, Пол клиента, Дата рождения, Описание, Вложения,
             Сегмент клиента, Страна, Область, Населённый пункт, Улица, Дом
    """
    batch_id = uuid.uuid4()

    # Create batch record
    batch = BatchUpload(id=batch_id, filename=filename, status="processing")
    db.add(batch)
    await db.flush()

    # Decode CSV
    encoding = _detect_encoding(file_bytes)
    text = file_bytes.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

    # Column mapping from Russian headers
    col_map = {}
    for col in df.columns:
        c = col.strip().lower()
        if "guid" in c:
            col_map[col] = "guid"
        elif "пол" in c or "gender" in c:
            col_map[col] = "gender"
        elif "рождени" in c or "birth" in c:
            col_map[col] = "birth_date"
        elif "описание" in c or "обращение" in c or "description" in c:
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

    batch.total_rows = len(df)
    await db.flush()

    # SSE: ingestion started
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="ingestion",
        status="in_progress",
        message=f"Ingesting {len(df)} tickets from '{filename}'",
        data={"total_rows": len(df), "filename": filename},
    )

    errors = []
    created_tickets: list[Ticket] = []
    # Track GUID counts within this batch for id_count_of_user
    guid_counts: dict[str, int] = {}
    if "guid" in df.columns:
        guid_counts = df["guid"].str.strip().value_counts().to_dict()

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # 1-based + header row
        try:
            description = _clean_str(row.get("description"))
            attachments = _parse_attachments(row.get("attachments"))

            # Spec edge case: both empty → still process (type=Консультация)
            # We always create the ticket, even with empty description

            guid = _clean_str(row.get("guid"))
            gender = _clean_str(row.get("gender"))
            birth_date = _parse_birth_date(row.get("birth_date"))
            age = _compute_age(birth_date)
            segment = _parse_segment(row.get("segment"))
            country = _clean_str(row.get("country"))
            region = _clean_str(row.get("region"))
            city = _clean_str(row.get("city"))
            street = _clean_str(row.get("street"))
            house = _clean_str(row.get("house"))

            # Feature engineering
            text_length = len(description) if description else 0
            text_length_times_age = float(text_length * age)
            id_count = guid_counts.get(guid, 0) if guid else 0

            ticket = Ticket(
                csv_row_index=row_num - 1,  # 0-based original index
                guid=guid,
                gender=gender,
                birth_date=birth_date,
                age=age,
                description=description,
                attachments=attachments,
                segment=segment,
                country=country,
                region=region,
                city=city,
                street=street,
                house=house,
                status=TicketStatusEnum.ingested,
                text_length=text_length,
                text_length_times_age=text_length_times_age,
                id_count_of_user=id_count,
            )
            db.add(ticket)
            await db.flush()

            # Processing state
            proc = ProcessingState(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage=ProcessingStageEnum.ingestion,
                status=StageStatusEnum.completed,
                progress_pct=100.0,
                message=f"Row {row_num} ingested",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            db.add(proc)

            created_tickets.append(ticket)
            batch.processed_rows += 1

            # SSE per-row
            await sse_manager.send_update(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage="ingestion",
                status="completed",
                message=f"Row {row_num} ingested",
                data={
                    "row": row_num,
                    "guid": guid,
                    "csv_row_index": ticket.csv_row_index,
                    "text_length": text_length,
                    "age": age,
                    "segment": segment.value if segment else None,
                },
            )

        except Exception as e:
            errors.append({"row": row_num, "error": str(e)})
            batch.failed_rows += 1
            await sse_manager.send_update(
                ticket_id=uuid.UUID(int=0),
                batch_id=batch_id,
                stage="ingestion",
                status="failed",
                message=f"Row {row_num} failed: {str(e)}",
                data={"row": row_num},
            )

    # Finalize batch
    batch.status = "completed" if not errors else "completed_with_errors"
    batch.error_log = errors
    batch.completed_at = datetime.utcnow()
    await db.flush()

    # SSE: batch complete
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="ingestion",
        status="completed",
        message=f"Batch complete: {batch.processed_rows}/{batch.total_rows}",
        data={
            "processed": batch.processed_rows,
            "failed": batch.failed_rows,
            "total": batch.total_rows,
        },
    )

    return {
        "batch_id": batch_id,
        "total_rows": batch.total_rows,
        "processed_rows": batch.processed_rows,
        "failed_rows": batch.failed_rows,
        "errors": errors,
    }
