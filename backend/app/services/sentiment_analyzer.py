"""
T6 — Sentiment Analysis via OpenRouter or Groq.

Runs in PARALLEL with T5 (Main LLM) and T7 (Geocoding).
Separate, focused model call for sentiment detection.
Uses Groq (llama3-8b-8192) when GROQ_API_KEY is set; otherwise OpenRouter.

Output: sentiment (позитивный/нейтральный/негативный) + confidence score.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sse_manager import sse_manager
from app.models.models import (
    AIAnalysis, ProcessingState, ProcessingStageEnum,
    StageStatusEnum, SentimentEnum, Ticket,
)
from app.models.schemas import SentimentResult

settings = get_settings()

# English -> Russian (our stored enum values)
_GROQ_TO_SENTIMENT = {
    "positive": SentimentEnum.позитивный.value,
    "neutral": SentimentEnum.нейтральный.value,
    "negative": SentimentEnum.негативный.value,
}

SENTIMENT_PROMPT_OPENROUTER = """Analyze the sentiment of this customer support ticket for a financial broker.

TICKET TEXT:
{ticket_text}

Classify sentiment as exactly one of:
- "позитивный" — grateful, satisfied, polite inquiry
- "нейтральный" — factual, no strong emotion, information request
- "негативный" — angry, frustrated, threatening, dissatisfied

Consider:
- Exclamation marks and ALL CAPS indicate stronger emotion
- Threats (суд, жалоба, прокуратура) = негативный
- Polite requests (пожалуйста, спасибо, буду благодарна) = позитивный
- Simple questions = нейтральный

Return ONLY valid JSON:
{{
  "sentiment": "позитивный" | "нейтральный" | "негативный",
  "confidence": 0.0-1.0
}}"""

SENTIMENT_PROMPT_GROQ = """Analyze the sentiment of the following support ticket.
Respond strictly in JSON with "sentiment" (value "positive", "neutral", or "negative") and "confidence" (0.0-1.0).

Ticket:
{ticket_text}"""


def _analyze_sentiment_groq_sync(ticket_text: str) -> dict:
    """Synchronous Groq call (run in thread from async)."""
    from groq import Groq
    client = Groq(api_key=settings.GROQ_API_KEY)
    prompt = SENTIMENT_PROMPT_GROQ.format(ticket_text=ticket_text or "(empty ticket body)")
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=settings.GROQ_SENTIMENT_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def _analyze_sentiment_groq(ticket_text: str) -> SentimentResult:
    """Run Groq sentiment in thread; map English -> Russian and normalize."""
    raw = await asyncio.to_thread(_analyze_sentiment_groq_sync, ticket_text)
    sentiment_en = (raw.get("sentiment") or "neutral").strip().lower()
    sentiment = _GROQ_TO_SENTIMENT.get(sentiment_en, SentimentEnum.нейтральный.value)
    confidence = float(raw.get("confidence", 0.9))
    confidence = max(0.0, min(1.0, confidence))
    return SentimentResult(sentiment=sentiment, confidence=confidence)


async def _analyze_sentiment_openrouter(ticket_text: str) -> SentimentResult:
    """OpenRouter sentiment (existing logic)."""
    prompt = SENTIMENT_PROMPT_OPENROUTER.format(
        ticket_text=ticket_text or "(empty ticket body)"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.OPENROUTER_SENTIMENT_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a sentiment analysis system. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 100,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data= response.json()

    content = data["choices"][0]["message"]["content"]
    result = json.loads(content)
    sentiment = result.get("sentiment", "нейтральный")
    valid_sentiments = [s.value for s in SentimentEnum]
    if sentiment not in valid_sentiments:
        sentiment = "нейтральный"
    return SentimentResult(
        sentiment=sentiment,
        confidence=float(result.get("confidence", 0.5)),
    )


async def analyze_sentiment(ticket_text: str) -> SentimentResult:
    """
    Call sentiment model. Uses Groq when GROQ_API_KEY is set in .env; otherwise OpenRouter.
    Returns sentiment (позитивный/нейтральный/негативный) + confidence.
    """
    s = get_settings()
    if s.GROQ_API_KEY and s.GROQ_API_KEY.strip():
        return await _analyze_sentiment_groq(ticket_text)
    return await _analyze_sentiment_openrouter(ticket_text)


async def analyze_sentiment_db(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> SentimentResult:
    """
    Run sentiment analysis and store in AI analysis record.
    """
    proc = ProcessingState(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage=ProcessingStageEnum.sentiment_analysis,
        status=StageStatusEnum.in_progress,
        started_at=datetime.utcnow(),
    )
    db.add(proc)
    await db.flush()

    start_time = time.time()

    try:
        text = ticket.description_anonymized or ticket.description or ""
        result = await analyze_sentiment(text)
        elapsed_ms = int((time.time() - start_time) * 1000)

        # Update AI analysis
        if ticket.ai_analysis:
            analysis = ticket.ai_analysis
        else:
            analysis = AIAnalysis(ticket_id=ticket.id)
            db.add(analysis)

        analysis.sentiment = result.sentiment
        analysis.sentiment_confidence = result.confidence

        proc.status = StageStatusEnum.completed
        proc.completed_at = datetime.utcnow()
        proc.progress_pct = 100.0
        proc.message = f"Sentiment: {result.sentiment} ({result.confidence:.2f}), {elapsed_ms}ms"
        await db.flush()

        # SSE
        await sse_manager.send_update(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage="sentiment_analysis",
            status="completed",
            field="sentiment",
            data={
                "sentiment": result.sentiment,
                "confidence": result.confidence,
            },
        )

        return result

    except Exception as e:
        proc.status = StageStatusEnum.failed
        proc.completed_at = datetime.utcnow()
        proc.error_detail = str(e)
        await db.flush()

        await sse_manager.send_update(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage="sentiment_analysis",
            status="failed",
            message=str(e),
        )

        return SentimentResult(sentiment="нейтральный", confidence=0.0)