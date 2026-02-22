"""
Step 4: Feature extraction with LLM calling

Processes the non-spam tickets to get:
- Sentiment
- Type
- Ticket Language (label + actual language - the handling of Uzbek and other non RU, ENG, KZ langauges)
- Needs Data Change Binary Variable
- Summary of the Ticket
- Explanation to be Passed on Admin Panel Later

"""

import asyncio
import base64
import json
import logging
import time
from pathlib import Path

import httpx

from app.core.config import get_settings

log = logging.getLogger("fire.llm_analysis")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

VALID_TYPES = [
    "Жалоба",
    "Смена данных",
    "Консультация",
    "Претензия",
    "Неработоспособность приложения",
    "Мошеннические действия",
    "Спам",
]

_TYPE_NORMALIZE = {
    "жалоба": "Жалоба",
    "смена_данных": "Смена данных",
    "смена данных": "Смена данных",
    "консультация": "Консультация",
    "претензия": "Претензия",
    "неработоспособность": "Неработоспособность приложения",
    "неработоспособность приложения": "Неработоспособность приложения",
    "мошенничество": "Мошеннические действия",
    "мошеннические действия": "Мошеннические действия",
    "спам": "Спам",
}

VALID_SENTIMENTS = ["Негативный", "Нейтральный", "Позитивный"]

_SENTIMENT_NORMALIZE = {
    "негативный": "Негативный",
    "нейтральный": "Нейтральный",
    "позитивный": "Позитивный",
    "negative": "Негативный",
    "neutral": "Нейтральный",
    "positive": "Позитивный",
}

_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

ANALYSIS_PROMPT = """You are a ticket classification system for Freedom Finance (a financial broker in Kazakhstan).
Analyze the following support ticket and return a JSON response.

TICKET TEXT:
{ticket_text}

{attachment_context}

CLIENT AGE: {age}
CLIENT SEGMENT: {segment}

INSTRUCTIONS:

1. **type** — classify into EXACTLY one of:
   - "Жалоба" (complaint — client unhappy about service quality, delays, errors)
   - "Смена данных" (data change — phone/email/password change, document update, personal info)
   - "Консультация" (consultation — question, how-to, information request)
   - "Претензия" (formal claim — demanding money back, threatening legal action)
   - "Неработоспособность приложения" (app malfunction — can't login, crashes, technical bugs)
   - "Мошеннические действия" (fraud — unauthorized access, suspicious transactions)
   - "Спам" (spam — advertising, promo. NOT angry clients!)

   CRITICAL: "ВЕРНИТЕ ДЕНЬГИ!!!" or "125$ не пришло" are NOT spam — they are claims/complaints.

2. **sentiment** — emotional tone of the ticket:
   - "Негативный" — anger, frustration, threats, urgency, complaints, demands
   - "Нейтральный" — factual, calm, informational, routine request
   - "Позитивный" — gratitude, satisfaction, polite praise
   Also return sentiment_confidence (0.0–1.0).

3. **language** — detect the language:
   - Labels: "RU" (Russian), "KZ" (Kazakh), "ENG" (English)
   - Turkic non-Kazakh (Uzbek, Turkish): age > 45 → "KZ", age ≤ 45 → "ENG"
   - Non-Turkic non-Russian (Portuguese, German): always "ENG"
   - Transliterated Cyrillic in Latin → detect underlying language, apply rules above
   - Mixed: primary = language of substantive content (ignore signatures)
   Return: language_label, language_actual, language_is_mixed, language_note

4. **summary** — 1-2 sentences in Russian: what the client needs.

5. **explanation** — 1-2 sentences in Russian explaining your classification reasoning. Example: "Тип — Консультация, так как клиент задаёт вопрос о покупке акций и не выражает недовольства. Тональность нейтральная — вежливый информационный запрос."

6. **attachment_analysis** — if attachments mentioned, describe what they likely show. Otherwise null.

7. **needs_data_change** — 0 or 1. Set 1 if client needs personal data change (phone, email, password, documents). Example: "хотела изменить номер телефона" → 1.

Respond with ONLY valid JSON:
{{
  "type": "...",
  "sentiment": "...",
  "sentiment_confidence": 0.85,
  "language_label": "...",
  "language_actual": "...",
  "language_is_mixed": false,
  "language_note": "...",
  "summary": "...",
  "explanation": "...",
  "attachment_analysis": null,
  "needs_data_change": 0
}}"""


async def _call_openrouter(messages: list[dict], model: str | None = None) -> dict:
    settings = get_settings()
    llm_model = model or settings.OPENROUTER_MODEL
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": llm_model,
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 1000,
                        "response_format": {"type": "json_object"},
                    },
                )

                if response.status_code in (401, 400):
                    response.raise_for_status()

                if response.status_code in (429, 500, 502, 503, 504):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    last_error = f"HTTP {response.status_code}"
                    log.warning("OpenRouter HTTP %d — retry %d in %.1fs", response.status_code, attempt + 1, delay)
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                log.warning("OpenRouter %s — retry %d in %.1fs", type(e).__name__, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            raise

    raise RuntimeError(f"OpenRouter failed after {MAX_RETRIES} retries: {last_error}")


def _normalize_type(raw: str) -> str:
    key = raw.strip().lower()
    if key in _TYPE_NORMALIZE:
        return _TYPE_NORMALIZE[key]
    for valid in VALID_TYPES:
        if key in valid.lower() or valid.lower() in key:
            return valid
    return "Консультация"


def _normalize_sentiment(raw: str) -> str:
    key = raw.strip().lower()
    return _SENTIMENT_NORMALIZE.get(key, "Нейтральный")


def _load_image_base64(filename: str, uploads_dir: str = "/app/uploads") -> tuple[str, str] | None:
    ext = Path(filename).suffix.lower()
    mime = _IMAGE_EXTENSIONS.get(ext)
    if not mime:
        return None
    for path in [Path(uploads_dir) / filename, Path(filename)]:
        if path.is_file():
            try:
                data = path.read_bytes()
                return base64.b64encode(data).decode("ascii"), mime
            except Exception:
                pass
    return None


async def analyze_ticket(ticket: dict, uploads_dir: str = "/app/uploads") -> dict:
    start = time.time()

    text = ticket.get("description_anonymized") or ticket.get("description") or ""
    age = ticket.get("age")
    segment = ticket.get("segment", "Mass")
    attachments_raw = ticket.get("attachments")
    attachments = []
    if attachments_raw:
        if isinstance(attachments_raw, list):
            attachments = attachments_raw
        elif isinstance(attachments_raw, str):
            attachments = [a.strip() for a in attachments_raw.split(",") if a.strip()]

    attachment_context = ""
    image_parts: list[dict] = []

    if attachments:
        attachment_context = f"ATTACHMENTS: {', '.join(attachments)}"
        for fname in attachments:
            img = _load_image_base64(fname, uploads_dir)
            if img:
                b64, mime = img
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
                attachment_context += f"\n[Image '{fname}' attached — analyze its content]"

    prompt = ANALYSIS_PROMPT.format(
        ticket_text=text or "(empty ticket body)",
        attachment_context=attachment_context,
        age=age if age is not None else "unknown",
        segment=segment,
    )

    system_msg = {"role": "system", "content": "You are a precise ticket classification system. Return only valid JSON."}

    if image_parts:
        user_content = [{"type": "text", "text": prompt}] + image_parts
        user_msg = {"role": "user", "content": user_content}
    else:
        user_msg = {"role": "user", "content": prompt}

    try:
        result = await _call_openrouter([system_msg, user_msg])
    except Exception as e:
        elapsed = time.time() - start
        ticket["type"] = ticket.get("type") or "Консультация"
        ticket["sentiment"] = "Нейтральный"
        ticket["sentiment_confidence"] = 0.0
        ticket["language_label"] = "RU"
        ticket["language_actual"] = "russian"
        ticket["language_is_mixed"] = False
        ticket["language_note"] = f"LLM failed: {e}"
        ticket["summary"] = "Ошибка LLM — требуется ручная обработка."
        ticket["explanation"] = f"Ошибка при обращении к LLM: {e}. Установлены значения по умолчанию."
        ticket["attachment_analysis"] = None
        ticket["needs_data_change"] = False
        ticket["llm_latency_ms"] = int(elapsed * 1000)
        return ticket

    elapsed = time.time() - start

    detected_type = _normalize_type(result.get("type", "Консультация"))

    if ticket.get("is_spam"):
        detected_type = "Спам"

    ticket["type"] = detected_type
    ticket["sentiment"] = _normalize_sentiment(result.get("sentiment", "Нейтральный"))
    ticket["sentiment_confidence"] = min(1.0, max(0.0, float(result.get("sentiment_confidence", 0.5))))
    ticket["language_label"] = result.get("language_label", "RU")
    ticket["language_actual"] = result.get("language_actual", "russian")
    ticket["language_is_mixed"] = result.get("language_is_mixed", False)
    ticket["language_note"] = result.get("language_note")
    ticket["summary"] = result.get("summary", "")
    ticket["explanation"] = result.get("explanation", "")
    ticket["attachment_analysis"] = result.get("attachment_analysis")
    ticket["needs_data_change"] = bool(result.get("needs_data_change", 0))
    ticket["llm_latency_ms"] = int(elapsed * 1000)

    if ticket["needs_data_change"] and detected_type != "Смена данных":
        ticket["type"] = "Смена данных"
        ticket["explanation"] += " Тип переопределён на «Смена данных» по флагу needs_data_change."

    return ticket


async def analyze_batch(tickets: list[dict], concurrency: int = 5, uploads_dir: str = "/app/uploads") -> list[dict]:
    sem = asyncio.Semaphore(concurrency)

    async def _process(t: dict) -> dict:
        if t.get("is_spam"):
            return t
        async with sem:
            return await analyze_ticket(t, uploads_dir)

    return list(await asyncio.gather(*[_process(t) for t in tickets]))