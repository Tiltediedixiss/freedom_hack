"""
T5 - LLM Analysis via OpenRouter (type + language + summary).

Single call extracts:
  • type: one of 7 Russian types
  • language: complex detection with Turkic/transliteration rules
  • summary: 1-2 sentences + recommended action
  • attachment_analysis
  • needs_data_change, needs_location_routing flags

Sentiment is handled separately by T6 (sentiment_analyzer.py) in parallel.
Includes retry with exponential backoff for OpenRouter flakiness.
"""

import asyncio
import json
import logging
import time

import httpx

from app.core.config import get_settings
from app.models.models import TicketTypeEnum
from app.models.schemas import LLMAnalysisResult

log = logging.getLogger("pipeline.llm")
settings = get_settings()

# ── Retry config ──
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds

# ── Prompt template ──

ANALYSIS_PROMPT = """You are a ticket classification system for Freedom Finance (a financial broker in Kazakhstan).
Analyze the following support ticket and return a JSON response.

TICKET TEXT:
{ticket_text}

{attachment_context}

CLIENT AGE: {age}

INSTRUCTIONS:
1. **type** — classify into EXACTLY one of these types:
   - "жалоба" (complaint — client is unhappy about service, not formal claim)
   - "смена_данных" (data change — password reset, phone change, document update)
   - "консультация" (consultation — question, information request)
   - "претензия" (formal claim — demanding money back, threatening legal action)
   - "неработоспособность" (app malfunction — can't login, app errors, technical issues)
   - "мошенничество" (fraud — client reports unauthorized access, suspicious activity)
   - "спам" (spam — unsolicited promotional content, NOT angry client messages)

   CRITICAL: Angry messages like "ВЕРНИТЕ ДЕНЬГИ!!!" are NOT spam. Spam is promotional/bot content.

2. **language** — detect the language with these rules:
   - Standard: "RU" (Russian), "KZ" (Kazakh), "ENG" (English)
   - If Turkic but NOT Kazakh (e.g., Uzbek, Turkish): age > 45 → "KZ", age ≤ 45 → "ENG"
   - Non-standard non-Turkic (e.g., Portuguese): "ENG"
   - Transliterated Cyrillic in Latin (e.g., "Zdravstvuyte") → detect underlying language
   - Mixed: primary = language of substantive content (ignore signatures like "Best Regards")

   Return:
   - language_label: "RU" | "KZ" | "ENG"
   - language_actual: the actual detected language (e.g., "russian", "kazakh", "english", "uzbek")
   - language_is_mixed: true if multiple languages in substantive content
   - language_note: explanation of language decision (e.g., "Turkic age-based assignment", "Signature-only English ignored")

3. **summary** — 1-2 sentence summary in Russian of what the client needs + recommended next action for the manager.

4. **attachment_analysis** — if attachments are mentioned, describe what they likely contain. If no attachments, return null.

5. **needs_data_change** — binary 0 or 1. Set to 1 if the client needs to change personal data on the platform (phone number, email, password, documents, personal info update). Example: "я хотела изменить номер телефона со старого на новый" → 1. A client asking about stock purchases → 0. This flag determines routing to Глав спец managers.

6. **needs_location_routing** — binary 0 or 1. Set to 1 if the ticket requires routing to the nearest physical office (client mentions visiting an office, needs in-person document verification, references a physical location/branch). Set to 0 for purely online issues (app problems, account access, general questions). Most tickets will be 0.

EDGE CASES:
- If ticket text is empty but has attachments, base your analysis on attachment context.
- If both text and attachments are empty, return type="консультация", language_label="RU", and note the empty ticket.

Respond with ONLY valid JSON:
{{
  "type": "...",
  "language_label": "...",
  "language_actual": "...",
  "language_is_mixed": false,
  "language_note": "...",
  "summary": "...",
  "attachment_analysis": null,
  "needs_data_change": 0,
  "needs_location_routing": 0
}}"""


async def _call_openrouter(prompt: str) -> dict:
    """
    Call OpenRouter with retry + exponential backoff.
    Returns parsed JSON response.
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            log.debug("    OpenRouter attempt %d/%d (model=%s)", attempt + 1, MAX_RETRIES, settings.OPENROUTER_MODEL)
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.OPENROUTER_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a precise ticket classification system. Return only valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1000,
                        "response_format": {"type": "json_object"},
                    },
                )

                # Don't retry on 401 (auth error) or 400 (bad request)
                if response.status_code in (401, 400):
                    log.error("    OpenRouter auth/bad request: HTTP %d", response.status_code)
                    response.raise_for_status()

                # Retry on 429, 500, 502, 503, 504
                if response.status_code in (429, 500, 502, 503, 504):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    last_error = f"HTTP {response.status_code}"
                    log.warning("    OpenRouter HTTP %d — retrying in %.1fs", response.status_code, delay)
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
                log.warning("    OpenRouter %s — retrying in %.1fs", type(e).__name__, delay)
                await asyncio.sleep(delay)
                continue
            raise

    raise RuntimeError(f"OpenRouter failed after {MAX_RETRIES} retries: {last_error}")


async def analyze_ticket(
    ticket_text: str,
    age: int | None = None,
    attachments: list[str] | None = None,
) -> LLMAnalysisResult:
    """
    Call OpenRouter LLM to analyze a ticket (type + language + sentiment + summary).
    Single call replaces the old separate T5 + T6 calls.
    """
    attachment_context = ""
    if attachments:
        attachment_context = f"ATTACHMENTS: {', '.join(attachments)}"

    prompt = ANALYSIS_PROMPT.format(
        ticket_text=ticket_text or "(empty ticket body)",
        attachment_context=attachment_context,
        age=age if age is not None else "unknown",
    )

    result = await _call_openrouter(prompt)

    # Validate type
    valid_types = [t.value for t in TicketTypeEnum]
    detected_type = result.get("type", "консультация")
    if detected_type not in valid_types:
        detected_type = "консультация"

    return LLMAnalysisResult(
        detected_type=detected_type,
        language_label=result.get("language_label", "RU"),
        language_actual=result.get("language_actual", "russian"),
        language_is_mixed=result.get("language_is_mixed", False),
        language_note=result.get("language_note"),
        summary=result.get("summary", ""),
        attachment_analysis=result.get("attachment_analysis"),
        needs_data_change=bool(result.get("needs_data_change", 0)),
        needs_location_routing=bool(result.get("needs_location_routing", 0)),
    )
