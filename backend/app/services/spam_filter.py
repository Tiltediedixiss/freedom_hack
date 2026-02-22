import re
import httpx
import logging
from dataclasses import dataclass

from app.core.config import get_settings

log = logging.getLogger("pipeline.spam")

SPAM_MODEL = "meta-llama/llama-3.1-8b-instruct"

SPAM_PROMPT = """You are a spam classifier for a financial broker's support system. 
Classify the following customer ticket as SPAM or NOT_SPAM.

SPAM means: advertising, promotional offers, product sales, unsolicited marketing, irrelevant commercial content.
NOT_SPAM means: any actual customer request, complaint, question, claim — even if short, angry, or poorly written.

IMPORTANT: Short angry messages like "ВЕРНИТЕ 500$!!!" are NOT spam. Legitimate complaints are NOT spam.

Ticket text:
---
{text}
---

Respond with exactly one word: SPAM or NOT_SPAM"""

_URL_RE = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_INVISIBLE_RE = re.compile(r'[\u2800-\u28FF\u200B\u200C\u200D\uFEFF]')
_PROMO_RE = re.compile(
    r'скидк|акци[яи]|промокод|распродаж|бесплатн|предложени|'
    r'sale|discount|promo|free offer|buy now|limited time|'
    r'реклам|оптов|со склад|выгодное предложение|специальные цены|',
    re.IGNORECASE,
)


@dataclass
class SpamResult:
    is_spam: bool
    probability: float
    reason: str


def _structural_check(text: str) -> SpamResult | None:
    if not text or not text.strip():
        return SpamResult(True, 1.0, "Empty body")

    stripped = text.strip()
    if len(stripped) < 3:
        return SpamResult(True, 1.0, f"Too short ({len(stripped)} chars)")

    invisible_count = len(_INVISIBLE_RE.findall(stripped))
    url_count = len(_URL_RE.findall(stripped))
    promo_count = len(_PROMO_RE.findall(stripped))

    if invisible_count > 10 and url_count >= 1:
        return SpamResult(True, 0.99, f"Invisible chars ({invisible_count}) + URL — structural spam")

    if promo_count >= 3 and url_count >= 1:
        return SpamResult(True, 0.95, f"Promo keywords ({promo_count}) + URL — structural spam")

    if invisible_count > 30:
        return SpamResult(True, 0.95, f"Excessive invisible chars ({invisible_count}) — structural spam")

    return None


async def _llm_check(text: str) -> SpamResult:
    settings = get_settings()
    cleaned = _URL_RE.sub('[URL]', text)
    cleaned = _INVISIBLE_RE.sub('', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()[:500]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": SPAM_MODEL,
                    "messages": [{"role": "user", "content": SPAM_PROMPT.format(text=cleaned)}],
                    "max_tokens": 5,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip().upper()

            is_spam = "SPAM" in answer and "NOT" not in answer
            return SpamResult(
                is_spam=is_spam,
                probability=0.85 if is_spam else 0.15,
                reason=f"LLM ({SPAM_MODEL}): {answer}",
            )
    except Exception as e:
        log.warning("Spam LLM call failed: %s — passing ticket through", e)
        return SpamResult(False, 0.0, f"LLM error: {e} — defaulting to not spam")


async def detect_spam(text: str) -> SpamResult:
    structural = _structural_check(text)
    if structural:
        return structural

    return await _llm_check(text)


def detect_spam_sync(text: str) -> SpamResult:
    structural = _structural_check(text)
    if structural:
        return structural

    import httpx as httpx_sync
    settings = get_settings()
    cleaned = _URL_RE.sub('[URL]', text)
    cleaned = _INVISIBLE_RE.sub('', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()[:500]

    try:
        resp = httpx_sync.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": SPAM_MODEL,
                "messages": [{"role": "user", "content": SPAM_PROMPT.format(text=cleaned)}],
                "max_tokens": 5,
                "temperature": 0,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        is_spam = "SPAM" in answer and "NOT" not in answer
        return SpamResult(is_spam=is_spam, probability=0.85 if is_spam else 0.15, reason=f"LLM: {answer}")
    except Exception as e:
        log.warning("Spam LLM call failed: %s", e)
        return SpamResult(False, 0.0, f"LLM error — defaulting to not spam")


SPAM_TICKET_DEFAULTS = {
    "type": "Спам",
    "sentiment": "Нейтральный",
    "sentiment_confidence": 0.0,
    "language_label": "RU",
    "language_actual": None,
    "language_is_mixed": False,
    "language_note": "Spam — language detection skipped",
    "summary": "Тикет классифицирован как спам и исключён из маршрутизации.",
    "attachment_analysis": None,
    "priority_final": 1.0,
    "is_spam": True,
}


def fill_spam_ticket(ticket: dict, result: SpamResult) -> dict:
    ticket.update(SPAM_TICKET_DEFAULTS)
    ticket["spam_probability"] = result.probability
    ticket["spam_reason"] = result.reason
    ticket["priority_breakdown"] = {
        "segment": 0, "type": 0, "sentiment": 0, "age": 0,
        "repeat_client": 0, "base_total": 0,
        "extra_expansion": 0, "extra_young_vip": 0,
        "extra_fifo": 0, "extra_total": 0,
        "fraud_floor_applied": False, "final": 1.0,
        "note": f"Spam — skipped scoring. Reason: {result.reason}",
    }
    return ticket