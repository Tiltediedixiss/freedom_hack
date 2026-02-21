"""
T6 — Sentiment Analysis via OpenRouter.

Runs in PARALLEL with T5 (Main LLM) and T7 (Geocoding).
Separate, focused model call for sentiment detection.

Output: sentiment (Позитивный/Нейтральный/Негативный) + confidence score.
"""

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

SENTIMENT_PROMPT = """Analyze the sentiment of this customer support ticket for a financial broker.

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


async def analyze_sentiment(ticket_text: str) -> SentimentResult:
    """
    Call OpenRouter sentiment model.
    Returns sentiment enum + confidence.
    """
    prompt = SENTIMENT_PROMPT.format(
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
        data = response.json()

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
