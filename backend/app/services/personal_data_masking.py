"""
Step 2: IIN Masking
Detects and replaces PII in ticket text before sending to external LLMs.

- Regex: IIN (12 digits), phone (+7/8xxx), card numbers (16 digits), emails
- Tokens: [IIN_1], [PHONE_1], [CARD_1], [EMAIL_1]
- Re-hydration: replaces tokens back with originals after LLM returns
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sse_manager import sse_manager
from app.models.models import (
    PIIMapping,
    ProcessingState,
    ProcessingStageEnum,
    StageStatusEnum,
    Ticket,
)

settings = get_settings()

IIN_PATTERN = re.compile(r'(?<!\d)\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d[\s\-]?\d(?!\d)')
PHONE_PATTERN = re.compile(r'(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}')
CARD_PATTERN = re.compile(r'(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)')
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')


def _strip_separators(value: str) -> str:
    return re.sub(r'[\s\-]', '', value)


def _is_valid_iin(raw: str) -> bool:
    return len(_strip_separators(raw)) == 12


def _is_valid_card(raw: str) -> bool:
    return len(_strip_separators(raw)) == 16


@dataclass
class PIIDetection:
    start: int
    end: int
    original: str
    pii_type: str
    token: str = ""


@dataclass
class AnonymizationResult:
    anonymized_text: str = ""
    detections: list[PIIDetection] = field(default_factory=list)


def anonymize_text(text: str) -> AnonymizationResult:
    if not text:
        return AnonymizationResult(anonymized_text="")

    detections: list[PIIDetection] = []

    for pattern, pii_type, validator in [
        (IIN_PATTERN, "IIN", _is_valid_iin),
        (PHONE_PATTERN, "PHONE", None),
        (CARD_PATTERN, "CARD", _is_valid_card),
        (EMAIL_PATTERN, "EMAIL", None),
    ]:
        for match in pattern.finditer(text):
            if validator and not validator(match.group()):
                continue
            if not _overlaps(match.start(), match.end(), detections):
                detections.append(PIIDetection(
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    pii_type=pii_type,
                ))

    detections.sort(key=lambda d: d.start)

    type_counters: dict[str, int] = {}
    for det in detections:
        count = type_counters.get(det.pii_type, 0) + 1
        type_counters[det.pii_type] = count
        det.token = f"[{det.pii_type}_{count}]"

    anonymized = text
    for det in sorted(detections, key=lambda d: d.start, reverse=True):
        anonymized = anonymized[:det.start] + det.token + anonymized[det.end:]

    return AnonymizationResult(
        anonymized_text=anonymized,
        detections=detections,
    )


def rehydrate_text(text: str, mappings: list[dict]) -> str:
    if not text or not mappings:
        return text or ""
    result = text
    for m in mappings:
        result = result.replace(m["token"], m["original"])
    return result


def rehydrate_ticket(ticket: dict) -> None:
    """
    In-place rehydrate PII tokens in a ticket dict (used by file-based pipeline).
    Expects ticket to have _pii_detections (list of {token, original}) from anonymize step.
    """
    mappings = ticket.get("_pii_detections") or ticket.get("_pii_mappings") or []
    if not mappings:
        return
    for key in ("description_anonymized", "summary", "explanation"):
        if ticket.get(key):
            ticket[key] = rehydrate_text(str(ticket[key]), mappings)


def _overlaps(start: int, end: int, detections: list[PIIDetection]) -> bool:
    for d in detections:
        if start < d.end and end > d.start:
            return True
    return False


async def anonymize_ticket(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> AnonymizationResult:
    proc = ProcessingState(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage=ProcessingStageEnum.pii_anonymization,
        status=StageStatusEnum.in_progress,
        started_at=datetime.utcnow(),
    )
    db.add(proc)
    await db.flush()

    text = ticket.description or ""
    result = anonymize_text(text)

    ticket.description_anonymized = result.anonymized_text
    ticket.status = "pii_stripped"

    for det in result.detections:
        mapping = PIIMapping(
            ticket_id=ticket.id,
            token=det.token,
            original_value=det.original.encode("utf-8"),
            pii_type=det.pii_type,
        )
        db.add(mapping)

    proc.status = StageStatusEnum.completed
    proc.completed_at = datetime.utcnow()
    proc.progress_pct = 100.0
    proc.message = f"Anonymized {len(result.detections)} PII entities"
    await db.flush()

    await sse_manager.send_update(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage="pii_anonymization",
        status="completed",
        field="description_anonymized",
        message=f"{len(result.detections)} PII entities masked",
        data={
            "pii_count": len(result.detections),
            "types": list(set(d.pii_type for d in result.detections)),
            "csv_row_index": getattr(ticket, "csv_row_index", None),
        },
    )

    return result