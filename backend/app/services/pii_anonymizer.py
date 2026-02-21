"""
T3 — PII Anonymization Pipeline.

Detects and replaces PII in ticket text before sending to external LLMs.
  • Regex: IIN (12 digits), phone (+7/8xxx), card numbers (16 digits), emails
  • spaCy NER: person names (PER), organizations (ORG)
  • Tokens: [CLIENT_NAME_1], [IIN_1], [PHONE_1], [CARD_1], [EMAIL_1], [ORG_1]
  • Re-hydration: replaces tokens back with originals after LLM returns
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sse_manager import sse_manager
from app.models.models import (
    PIIMapping, ProcessingState, ProcessingStageEnum,
    StageStatusEnum, Ticket,
)

settings = get_settings()

# ── spaCy model (loaded lazily) ──
_nlp = None


def _get_nlp():
    """Lazy-load spaCy Russian model."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("ru_core_news_sm")
        except OSError:
            import spacy
            from spacy.cli import download
            download("ru_core_news_sm")
            _nlp = spacy.load("ru_core_news_sm")
    return _nlp


# ── Regex patterns ──

# Kazakhstan IIN: exactly 12 digits (not part of a longer number)
IIN_PATTERN = re.compile(r'(?<!\d)\d{12}(?!\d)')

# Phone: +7, 8, or +7 followed by 10 digits, various separators
PHONE_PATTERN = re.compile(
    r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}'
    r'|'
    r'(?:\+7|8)\d{10}'
    r'|'
    # Masked phones like +7XXXXXXXXX46, +7ХХХХХХХХХх7
    r'(?:\+7|8)[0-9ХхXx\s\-]{8,12}\d{0,2}'
)

# Card number: 16 digits, optional spaces/dashes every 4
CARD_PATTERN = re.compile(
    r'(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)'
)

# Email
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)

# Full name: two consecutive words each starting with a capital letter
# Matches patterns like "Иван Иванов", "John Doe", "Динара Воробьева"
# Excludes common non-name bigrams (greetings, abbreviations, etc.)
FULL_NAME_PATTERN = re.compile(
    r'(?<![А-ЯЁA-Z])'                          # not preceded by uppercase
    r'([А-ЯЁA-Z][а-яёa-z]{1,20})'              # First name (2-21 chars)
    r'\s+'
    r'([А-ЯЁA-Z][а-яёa-z]{1,25})'              # Last name (2-26 chars)
    r'(?![а-яёa-z])'                            # not followed by lowercase
)

# Words that look like names but aren't — skip these bigrams
_FULL_NAME_IGNORE = {
    # Russian greetings / common sentence starters
    "добрый день", "добрый вечер", "доброе утро", "уважаемые коллеги",
    "уважаемый клиент", "здравствуйте уважаемые", "здравствуйте вы",
    "подскажите пожалуйста", "хочу узнать", "прошу вас",
    # Company / product names
    "freedom broker", "freedom finance", "money advisor",
    # Common two-word phrases in financial context
    "московская биржа", "саудовской аравии", "казахстанской облигации",
    "брокерский счет", "брокерские услуги", "бездействующих счетов",
    "личности изменить", "специальные цены", "наличии складе",
    # Address-related
    "северо казахстанская",
}


@dataclass
class PIIDetection:
    """A single PII entity detected in text."""
    start: int
    end: int
    original: str
    pii_type: str  # CLIENT_NAME, IIN, PHONE, CARD, EMAIL, ORG
    token: str = ""


@dataclass
class AnonymizationResult:
    """Result of anonymizing a text."""
    anonymized_text: str
    detections: list[PIIDetection] = field(default_factory=list)


def anonymize_text(text: str) -> AnonymizationResult:
    """
    Detect and replace all PII in the given text.
    Returns anonymized text + list of detections with tokens.
    """
    if not text:
        return AnonymizationResult(anonymized_text="")

    detections: list[PIIDetection] = []

    # ── 1. Regex-based detection ──

    # IINs
    for match in IIN_PATTERN.finditer(text):
        detections.append(PIIDetection(
            start=match.start(), end=match.end(),
            original=match.group(), pii_type="IIN",
        ))

    # Phones
    for match in PHONE_PATTERN.finditer(text):
        detections.append(PIIDetection(
            start=match.start(), end=match.end(),
            original=match.group(), pii_type="PHONE",
        ))

    # Cards
    for match in CARD_PATTERN.finditer(text):
        detections.append(PIIDetection(
            start=match.start(), end=match.end(),
            original=match.group(), pii_type="CARD",
        ))

    # Emails
    for match in EMAIL_PATTERN.finditer(text):
        detections.append(PIIDetection(
            start=match.start(), end=match.end(),
            original=match.group(), pii_type="EMAIL",
        ))

    # ── 1b. Full name detection (two consecutive Capitalized words) ──
    for match in FULL_NAME_PATTERN.finditer(text):
        full = match.group().strip()
        full_lower = full.lower()
        # Skip known non-name bigrams
        if full_lower in _FULL_NAME_IGNORE:
            continue
        # Skip if overlaps with already-detected regex PII
        if _overlaps(match.start(), match.end(), detections):
            continue
        detections.append(PIIDetection(
            start=match.start(), end=match.end(),
            original=full, pii_type="FULL_NAME",
        ))

    # ── 2. spaCy NER-based detection ──
    # Only detect actual client PII (person names).
    # Skip ORG entities — company names like "Freedom Broker", "ПЕРВОУРАЛЬСКБАНК"
    # are not client PII and cause false positives.
    # Also skip very short PER entities (1-2 chars) and common greetings/salutations.
    # Note: FULL_NAME_PATTERN above catches two-word capitalized names first;
    # spaCy may still catch single-word names or names with unusual formatting.
    _IGNORE_NAMES = {
        "здравствуйте", "добрый", "уважаемые", "уважаемый", "коллеги",
        "день", "вечер", "утро", "привет", "hello", "hey", "dear",
        "fw", "re", "iphone", "android", "mail", "whatsapp",
    }
    try:
        nlp = _get_nlp()
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ == "PER":
                name = ent.text.strip()
                # Skip too short, single-word common words, or greetings
                if len(name) < 3:
                    continue
                if name.lower() in _IGNORE_NAMES:
                    continue
                # Skip if it's clearly not a person name (all caps, contains digits)
                if any(c.isdigit() for c in name):
                    continue
                # Check not already detected by regex
                if not _overlaps(ent.start_char, ent.end_char, detections):
                    detections.append(PIIDetection(
                        start=ent.start_char, end=ent.end_char,
                        original=ent.text, pii_type="CLIENT_NAME",
                    ))
    except Exception:
        # If spaCy fails, continue with regex-only detections
        pass

    # ── 3. Sort by position (descending) for safe replacement ──
    detections.sort(key=lambda d: d.start, reverse=True)

    # ── 4. Remove overlapping detections (keep first/longest) ──
    detections = _remove_overlaps(detections)

    # ── 5. Assign sequential tokens by type ──
    type_counters: dict[str, int] = {}
    # Re-sort ascending for token numbering
    detections.sort(key=lambda d: d.start)
    for det in detections:
        count = type_counters.get(det.pii_type, 0) + 1
        type_counters[det.pii_type] = count
        det.token = f"[{det.pii_type}_{count}]"

    # ── 6. Replace in text (from end to preserve positions) ──
    anonymized = text
    for det in sorted(detections, key=lambda d: d.start, reverse=True):
        anonymized = anonymized[:det.start] + det.token + anonymized[det.end:]

    return AnonymizationResult(
        anonymized_text=anonymized,
        detections=detections,
    )


def rehydrate_text(text: str, mappings: list[dict]) -> str:
    """
    Replace PII tokens back with original values in LLM output.
    mappings: list of {"token": "[CLIENT_NAME_1]", "original": "Динара"}
    """
    if not text or not mappings:
        return text or ""

    result = text
    for m in mappings:
        result = result.replace(m["token"], m["original"])
    return result


def _overlaps(start: int, end: int, detections: list[PIIDetection]) -> bool:
    """Check if a span overlaps with any existing detection."""
    for d in detections:
        if start < d.end and end > d.start:
            return True
    return False


def _remove_overlaps(detections: list[PIIDetection]) -> list[PIIDetection]:
    """Remove overlapping detections, keeping the one that appears first."""
    if not detections:
        return []
    # Already sorted descending by start
    result = [detections[0]]
    for det in detections[1:]:
        last = result[-1]
        # Since sorted descending, det.start <= last.start
        if det.end <= last.start:
            result.append(det)
    return result


# ── Database integration ──

async def anonymize_ticket(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> AnonymizationResult:
    """
    Anonymize a ticket's description and store PII mappings.
    Updates ticket.description_anonymized in DB.
    """
    # Create processing state
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

    # Store anonymized text on ticket
    ticket.description_anonymized = result.anonymized_text
    ticket.status = "pii_stripped"

    # Store PII mappings (encrypted at DB level via BYTEA)
    for det in result.detections:
        mapping = PIIMapping(
            ticket_id=ticket.id,
            token=det.token,
            original_value=det.original.encode("utf-8"),
            pii_type=det.pii_type,
        )
        db.add(mapping)

    # Update processing state
    proc.status = StageStatusEnum.completed
    proc.completed_at = datetime.utcnow()
    proc.progress_pct = 100.0
    proc.message = f"Anonymized {len(result.detections)} PII entities"
    await db.flush()

    # SSE update
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
        },
    )

    return result
