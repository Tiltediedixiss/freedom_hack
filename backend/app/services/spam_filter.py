"""
T4 - Spam Pre-Filter using pre-trained HuggingFace model.

Uses mrm8488/bert-tiny-finetuned-sms-spam-detection - a lightweight
BERT-based classifier pre-trained on the SMS Spam Collection dataset.

Combined with structural heuristics for multilingual edge cases:
  - Empty/ultra-short text -> spam
  - Invisible character padding (Braille) -> spam signal boost
  - URL-heavy text -> spam signal boost
  - Promotional keywords (RU/EN) -> spam signal boost
"""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("pipeline.spam")

from app.core.sse_manager import sse_manager
from app.models.models import (
    ProcessingState, ProcessingStageEnum, StageStatusEnum,
    Ticket, TicketStatusEnum, TicketTypeEnum,
)

# Pre-trained model (HuggingFace)
MODEL_NAME = "mrm8488/bert-tiny-finetuned-sms-spam-detection"

# Lazy-loaded pipeline
_classifier = None


@dataclass
class SpamResult:
    is_spam: bool
    probability: float
    reason: str


# Regex patterns for structural analysis
_URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_SAFELINKS_RE = re.compile(r'safelinks\.protection\.outlook', re.IGNORECASE)
_INVISIBLE_RE = re.compile(r'[\u2800-\u28FF\u200B\u200C\u200D\uFEFF\u00A0]')
_PROMO_RE = re.compile(
    r'скидк|акци[яи]|промокод|распродаж|бесплатн|предложени|'
    r'sale|discount|promo|free|offer|buy now|limited|'
    r'реклам|оптов|со склад|доставк|заказ|регистрац|'
    r'минимальный заказ|специальные цены|выгодное предложение|'
    r'день инвестора',
    re.IGNORECASE,
)


def _get_classifier():
    """Lazy-load the HuggingFace text-classification pipeline."""
    global _classifier
    if _classifier is None:
        from transformers import pipeline
        log.info("Loading pre-trained spam model: %s", MODEL_NAME)
        _classifier = pipeline(
            "text-classification",
            model=MODEL_NAME,
            truncation=True,
            max_length=512,
        )
        log.info("Spam model loaded successfully")
    return _classifier


def _clean_for_model(text: str) -> str:
    """Strip URLs and invisible chars for cleaner model input."""
    text = _URL_RE.sub(' ', text)
    text = _INVISIBLE_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _structural_score(text: str) -> tuple[float, list[str]]:
    """
    Compute structural spam signals (0.0-1.0).
    High-confidence structural patterns can override the model.
    """
    signals = []
    score = 0.0
    n = max(len(text), 1)

    # URL density
    urls = _URL_RE.findall(text)
    if urls:
        url_chars = sum(len(u) for u in urls)
        density = url_chars / n
        if density > 0.3:
            score += 0.3
            signals.append(f"url_density={density:.0%}")
        elif len(urls) >= 2:
            score += 0.15
            signals.append(f"urls={len(urls)}")
        else:
            score += 0.05
            signals.append(f"urls={len(urls)}")

    # SafeLinks (Outlook protection rewrites - strong spam indicator)
    if _SAFELINKS_RE.search(text):
        score += 0.3
        signals.append("safelinks")

    # Invisible characters (Braille U+2800..U+28FF, zero-width, NBSP)
    invisible = len(_INVISIBLE_RE.findall(text))
    if invisible > 5:
        score += 0.5
        signals.append(f"invisible_chars={invisible}")
    elif invisible > 0:
        score += 0.1
        signals.append(f"invisible_chars={invisible}")

    # Promotional keywords (RU + EN)
    promo_hits = len(_PROMO_RE.findall(text))
    if promo_hits >= 3:
        score += 0.4
        signals.append(f"promo_keywords={promo_hits}")
    elif promo_hits >= 1:
        score += 0.1
        signals.append(f"promo_keywords={promo_hits}")

    return min(score, 1.0), signals


def detect_spam(text: str) -> SpamResult:
    """
    Detect spam using pre-trained BERT model + structural heuristics.

    Scoring:
      combined = model_prob * 0.4 + struct_score * 0.6
      If struct_score >= 0.7 -> override to spam (structural certainty)

    Threshold: 0.50
    """
    if not text or not text.strip():
        return SpamResult(is_spam=True, probability=1.0, reason="Empty body")

    stripped = text.strip()
    if len(stripped) < 3:
        return SpamResult(
            is_spam=True, probability=1.0,
            reason=f"Too short ({len(stripped)} chars)",
        )

    # Structural analysis
    struct_score, struct_signals = _structural_score(stripped)

    # Structural override: very high structural confidence -> spam
    if struct_score >= 0.7:
        sig_str = ", ".join(struct_signals)
        return SpamResult(
            is_spam=True,
            probability=round(struct_score, 4),
            reason=f"Structural override: {struct_score:.2f} [{sig_str}]",
        )

    # Pre-trained model prediction
    cleaned = _clean_for_model(stripped)
    if len(cleaned) < 3:
        if struct_score >= 0.5:
            return SpamResult(
                is_spam=True, probability=round(struct_score, 4),
                reason=f"Structural spam (cleaned empty): [{', '.join(struct_signals)}]",
            )
        return SpamResult(
            is_spam=False, probability=round(struct_score, 4),
            reason="Cleaned text empty, low structural score",
        )

    clf = _get_classifier()
    result = clf(cleaned[:512])[0]

    # Model outputs: LABEL_0 = ham, LABEL_1 = spam
    label = result["label"]
    model_conf = result["score"]

    if label == "LABEL_1":  # spam
        model_spam_prob = model_conf
    else:  # ham
        model_spam_prob = 1.0 - model_conf

    # Combined score
    combined = min(model_spam_prob * 0.4 + struct_score * 0.6, 1.0)

    threshold = 0.50
    is_spam = combined >= threshold

    sig_str = ", ".join(struct_signals) if struct_signals else "none"
    reason = (
        f"bert-spam: model={model_spam_prob:.3f}, "
        f"struct={struct_score:.2f} [{sig_str}], "
        f"combined={combined:.3f}"
    )

    return SpamResult(
        is_spam=is_spam,
        probability=round(combined, 4),
        reason=reason,
    )


# Database integration

async def check_spam(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> SpamResult:
    """
    Check if a ticket is spam and update DB accordingly.
    Spam tickets: is_spam=True, type=spam, skip LLM pipeline.
    """
    proc = ProcessingState(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage=ProcessingStageEnum.spam_filter,
        status=StageStatusEnum.in_progress,
        started_at=datetime.utcnow(),
    )
    db.add(proc)
    await db.flush()

    text = ticket.description or ""
    result = detect_spam(text)

    ticket.is_spam = result.is_spam
    ticket.spam_probability = result.probability
    ticket.status = TicketStatusEnum.spam_checked

    if result.is_spam:
        ticket.ticket_type = TicketTypeEnum.спам

    proc.status = StageStatusEnum.completed
    proc.completed_at = datetime.utcnow()
    proc.progress_pct = 100.0
    proc.message = result.reason
    await db.flush()

    # SSE update
    await sse_manager.send_update(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage="spam_filter",
        status="completed",
        field="is_spam",
        message=result.reason,
        data={
            "is_spam": result.is_spam,
            "spam_probability": result.probability,
        },
    )

    return result
