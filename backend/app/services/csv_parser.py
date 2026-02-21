"""
T2 — CSV Parser & Data Ingestion Service.

Handles:
  • Parsing uploaded CSV files (tickets + managers)
  • Encoding detection (chardet)
  • Column mapping / normalization
  • Batch insert into PostgreSQL
  • Feature engineering (Stage 1): age, text_length_times_age, id_count_of_user
  • SSE progress broadcasting per row
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Any

import chardet
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sse_manager import sse_manager
from app.models.models import (
    BatchUpload,
    Manager,
    ProcessingState,
    ProcessingStageEnum,
    StageStatusEnum,
    Ticket,
    TicketStatusEnum,
)


# ─── Column mapping: CSV header → DB field ───────────────────────────

TICKET_COLUMN_MAP: dict[str, str] = {
    # Flexible mappings — lowercase CSV header → model attribute
    "id": "external_id",
    "external_id": "external_id",
    "ticket_id": "external_id",
    "name": "user_name",
    "user_name": "user_name",
    "username": "user_name",
    "full_name": "user_name",
    "email": "user_email",
    "user_email": "user_email",
    "mail": "user_email",
    "age": "user_age",
    "user_age": "user_age",
    "subject": "subject",
    "title": "subject",
    "body": "body",
    "text": "body",
    "message": "body",
    "description": "body",
    "content": "body",
    "language": "language",
    "lang": "language",
    "latitude": "latitude",
    "lat": "latitude",
    "longitude": "longitude",
    "lon": "longitude",
    "lng": "longitude",
    "address": "address",
    "location": "address",
    "attachment": "attachment_urls",
    "attachments": "attachment_urls",
    "attachment_url": "attachment_urls",
    "attachment_urls": "attachment_urls",
    "file": "attachment_urls",
    "files": "attachment_urls",
}

MANAGER_COLUMN_MAP: dict[str, str] = {
    "id": "external_id",  # We won't use this as PK; just store reference
    "name": "name",
    "manager_name": "name",
    "full_name": "name",
    "email": "email",
    "mail": "email",
    "phone": "phone",
    "telephone": "phone",
    "competencies": "competencies",
    "skills": "competencies",
    "competency": "competencies",
    "latitude": "latitude",
    "lat": "latitude",
    "longitude": "longitude",
    "lon": "longitude",
    "lng": "longitude",
    "max_tickets": "max_tickets_per_day",
    "max_tickets_per_day": "max_tickets_per_day",
    "capacity": "max_tickets_per_day",
    "active": "is_active",
    "is_active": "is_active",
}


def _detect_encoding(raw_bytes: bytes) -> str:
    """Detect file encoding with chardet, fallback to utf-8."""
    result = chardet.detect(raw_bytes)
    return result.get("encoding") or "utf-8"


def _normalize_columns(df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """Rename CSV columns to DB field names using the mapping dict."""
    # Lowercase & strip whitespace from headers
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    rename = {}
    for csv_col in df.columns:
        if csv_col in column_map:
            rename[csv_col] = column_map[csv_col]

    df = df.rename(columns=rename)

    # De-duplicate columns (keep first occurrence)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def _parse_attachment_urls(value: Any) -> list[str]:
    """Parse attachment URLs from various CSV formats."""
    if pd.isna(value) or value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    # Could be semicolon, comma, or pipe separated
    for sep in [";", "|", ","]:
        if sep in s:
            return [u.strip() for u in s.split(sep) if u.strip()]
    return [s]


def _safe_float(value: Any) -> float | None:
    """Safely convert to float."""
    if pd.isna(value) or value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Safely convert to int."""
    if pd.isna(value) or value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_competencies(value: Any) -> list[str]:
    """Parse competencies list from CSV."""
    if pd.isna(value) or value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    for sep in [";", "|", ","]:
        if sep in s:
            return [c.strip() for c in s.split(sep) if c.strip()]
    return [s]


# ─── Main ingestion functions ────────────────────────────────────────


async def ingest_tickets_csv(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
) -> dict:
    """
    Parse a tickets CSV and insert rows into the database.
    Returns batch metadata.
    """
    batch_id = uuid.uuid4()

    # ── Create batch record ──
    batch = BatchUpload(
        id=batch_id,
        filename=filename,
        status="processing",
    )
    db.add(batch)
    await db.flush()

    # ── Decode & parse CSV ──
    encoding = _detect_encoding(file_bytes)
    text_content = file_bytes.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text_content), dtype=str, keep_default_na=False)
    df = _normalize_columns(df, TICKET_COLUMN_MAP)

    batch.total_rows = len(df)
    await db.flush()

    # Broadcast: ingestion started
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),  # placeholder for batch-level event
        batch_id=batch_id,
        stage="ingestion",
        status="in_progress",
        message=f"Ingesting {len(df)} tickets from '{filename}'",
        data={"total_rows": len(df), "filename": filename},
    )

    errors = []
    created_tickets: list[Ticket] = []

    for idx, row in df.iterrows():
        try:
            # ── Extract fields ──
            body = str(row.get("body", "")).strip()
            if not body:
                errors.append({"row": int(idx) + 2, "error": "Empty body — skipped"})
                batch.failed_rows += 1
                continue

            user_age = _safe_int(row.get("user_age"))
            text_length = len(body)
            text_length_times_age = (
                float(text_length * user_age) if user_age is not None else None
            )

            lat = _safe_float(row.get("latitude"))
            lon = _safe_float(row.get("longitude"))

            attachment_urls = _parse_attachment_urls(row.get("attachment_urls"))

            ticket = Ticket(
                external_id=str(row.get("external_id", "")).strip() or None,
                user_name=str(row.get("user_name", "")).strip() or None,
                user_email=str(row.get("user_email", "")).strip() or None,
                user_age=user_age,
                subject=str(row.get("subject", "")).strip() or None,
                body=body,
                language=str(row.get("language", "")).strip() or None,
                latitude=lat,
                longitude=lon,
                geo_point=f"SRID=4326;POINT({lon} {lat})" if lat and lon else None,
                address=str(row.get("address", "")).strip() or None,
                attachment_urls=attachment_urls,
                status=TicketStatusEnum.ingested,
                text_length=text_length,
                text_length_times_age=text_length_times_age,
            )
            db.add(ticket)
            await db.flush()  # Get ticket.id

            # ── Create initial processing state ──
            proc_state = ProcessingState(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage=ProcessingStageEnum.ingestion,
                status=StageStatusEnum.completed,
                progress_pct=100.0,
                message="Ticket ingested from CSV",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            db.add(proc_state)

            created_tickets.append(ticket)
            batch.processed_rows += 1

            # ── SSE: per-row update ──
            await sse_manager.send_update(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage="ingestion",
                status="completed",
                message=f"Row {int(idx) + 2} ingested",
                data={
                    "row": int(idx) + 2,
                    "external_id": ticket.external_id,
                    "text_length": text_length,
                },
            )

        except Exception as e:
            errors.append({"row": int(idx) + 2, "error": str(e)})
            batch.failed_rows += 1
            await sse_manager.send_update(
                ticket_id=uuid.UUID(int=0),
                batch_id=batch_id,
                stage="ingestion",
                status="failed",
                message=f"Row {int(idx) + 2} failed: {str(e)}",
                data={"row": int(idx) + 2},
            )

    # ── Stage 1: Feature Engineering — id_count_of_user ──
    # Count historical tickets per user email
    await _compute_user_ticket_counts(db, created_tickets)

    # ── Finalize batch ──
    batch.status = "completed" if not errors else "completed_with_errors"
    batch.error_log = errors
    batch.completed_at = datetime.utcnow()
    await db.flush()

    # Broadcast: ingestion complete
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="ingestion",
        status="completed",
        message=f"Batch ingestion complete: {batch.processed_rows}/{batch.total_rows} rows",
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


async def _compute_user_ticket_counts(
    db: AsyncSession, tickets: list[Ticket]
):
    """
    Stage 1 — Feature Engineering: id_count_of_user.
    For each ticket, count how many tickets exist for the same user_email.
    """
    emails = [t.user_email for t in tickets if t.user_email]
    if not emails:
        return

    # Get counts per email in one query
    result = await db.execute(
        select(Ticket.user_email, func.count(Ticket.id).label("cnt"))
        .where(Ticket.user_email.in_(emails))
        .group_by(Ticket.user_email)
    )
    email_counts: dict[str, int] = {row.user_email: row.cnt for row in result}

    # Update each ticket
    for ticket in tickets:
        if ticket.user_email and ticket.user_email in email_counts:
            ticket.id_count_of_user = email_counts[ticket.user_email]
            await db.flush()


async def ingest_managers_csv(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
) -> dict:
    """
    Parse a managers CSV and upsert into database.
    Returns import metadata.
    """
    encoding = _detect_encoding(file_bytes)
    text_content = file_bytes.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text_content), dtype=str, keep_default_na=False)
    df = _normalize_columns(df, MANAGER_COLUMN_MAP)

    imported = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            name = str(row.get("name", "")).strip()
            if not name:
                errors.append({"row": int(idx) + 2, "error": "Empty name — skipped"})
                continue

            lat = _safe_float(row.get("latitude"))
            lon = _safe_float(row.get("longitude"))
            competencies = _parse_competencies(row.get("competencies"))

            max_tickets = _safe_int(row.get("max_tickets_per_day"))
            is_active_raw = str(row.get("is_active", "true")).strip().lower()
            is_active = is_active_raw not in ("false", "0", "no", "n")

            email = str(row.get("email", "")).strip() or None

            # Check for existing manager by email (upsert logic)
            existing = None
            if email:
                result = await db.execute(
                    select(Manager).where(Manager.email == email)
                )
                existing = result.scalar_one_or_none()

            if existing:
                existing.name = name
                existing.phone = str(row.get("phone", "")).strip() or existing.phone
                existing.competencies = competencies or existing.competencies
                existing.latitude = lat if lat is not None else existing.latitude
                existing.longitude = lon if lon is not None else existing.longitude
                if lat and lon:
                    existing.geo_point = f"SRID=4326;POINT({lon} {lat})"
                existing.max_tickets_per_day = max_tickets or existing.max_tickets_per_day
                existing.is_active = is_active
                existing.updated_at = datetime.utcnow()
            else:
                manager = Manager(
                    name=name,
                    email=email,
                    phone=str(row.get("phone", "")).strip() or None,
                    competencies=competencies,
                    latitude=lat,
                    longitude=lon,
                    geo_point=f"SRID=4326;POINT({lon} {lat})" if lat and lon else None,
                    max_tickets_per_day=max_tickets or 20,
                    is_active=is_active,
                )
                db.add(manager)

            imported += 1

        except Exception as e:
            errors.append({"row": int(idx) + 2, "error": str(e)})

    await db.flush()

    return {
        "total_imported": imported,
        "errors": errors,
        "filename": filename,
    }
