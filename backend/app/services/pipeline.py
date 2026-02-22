"""
Pipeline Orchestrator — coordinates T4→T3→(T5‖T6‖T7) per ticket.

For each ticket:
  1. Spam pre-filter (T4) → if spam, skip to storage
  2. PII anonymize (T3) → strip personal data
  3. Parallel: asyncio.gather(LLM(T5), Sentiment(T6), Geocode(T7))
     All three run simultaneously — total latency ≈ max(LLM, Sentiment, Geocode).
  4. Merge results back to main session
  5. PII re-hydrate tokens in LLM summary
  6. Store all results & SSE broadcast
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.sse_manager import sse_manager
from app.models.models import (
    AIAnalysis, BatchUpload, Ticket, TicketStatusEnum,
    PIIMapping, ProcessingState, ProcessingStageEnum, StageStatusEnum,
)
from app.models.schemas import LLMAnalysisResult, GeocodingResult, SentimentResult
from app.services.spam_prefiltering import check_spam
from app.services.personal_data_masking import anonymize_ticket, rehydrate_text
from app.services.llm_processing import analyze_ticket as llm_analyze_api
from app.services.sentiment_analyzer import analyze_sentiment as sentiment_analyze_api
from app.services.geocoder import geocode_address
from app.services.geo_filtering import assign_ticket_to_nearest

log = logging.getLogger("pipeline")


async def _run_llm(ticket_text: str, age: int | None, attachments: list[str] | None):
    """Run LLM analysis (type + language + summary). Sentiment is separate."""
    start = time.time()
    log.info("  [LLM] calling OpenRouter (text=%d chars, age=%s, attachments=%s)",
             len(ticket_text or ""), age, attachments)
    try:
        result = await llm_analyze_api(
            ticket_text=ticket_text,
            age=age,
            attachments=attachments,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        log.info("  [LLM] ✓ %dms — type=%s, lang=%s, data_change=%s, location=%s",
                 elapsed_ms, result.detected_type, result.language_label,
                 result.needs_data_change, result.needs_location_routing)
        log.info("  [LLM]   summary: %.120s", result.summary)
        return {"result": result, "elapsed_ms": elapsed_ms, "error": None}
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error("  [LLM] ✗ FAILED %dms — %s", elapsed_ms, e)
        return {
            "result": LLMAnalysisResult(
                detected_type="консультация",
                language_label="RU",
                language_actual="russian",
                summary=f"Ошибка анализа: {str(e)}",
            ),
            "elapsed_ms": elapsed_ms,
            "error": str(e),
        }


async def _run_sentiment(ticket_text: str):
    """Run separate sentiment analysis via OpenRouter (T6)."""
    start = time.time()
    log.info("  [SENTIMENT] calling OpenRouter (text=%d chars)", len(ticket_text or ""))
    try:
        result = await sentiment_analyze_api(ticket_text)
        elapsed_ms = int((time.time() - start) * 1000)
        log.info("  [SENTIMENT] ✓ %dms — %s (confidence=%.2f)",
                 elapsed_ms, result.sentiment, result.confidence)
        return {"result": result, "elapsed_ms": elapsed_ms, "error": None}
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error("  [SENTIMENT] ✗ FAILED %dms — %s", elapsed_ms, e)
        return {
            "result": SentimentResult(sentiment="нейтральный", confidence=0.0),
            "elapsed_ms": elapsed_ms,
            "error": str(e),
        }


async def _run_geocode(country, region, city, street, house):
    """Run geocoding API call with its own DB session for cache."""
    start = time.time()
    addr_parts = [p for p in [country, region, city, street, house] if p]
    log.info("  [GEO] geocoding: %s", ", ".join(addr_parts) or "(empty)")
    try:
        async with async_session_factory() as geo_db:
            result = await geocode_address(
                country=country, region=region, city=city,
                street=street, house=house, db=geo_db,
            )
            await geo_db.commit()
        elapsed_ms = int((time.time() - start) * 1000)
        log.info("  [GEO] ✓ %dms — provider=%s, status=%s, lat=%.4f, lon=%.4f",
                 elapsed_ms, result.provider, result.address_status,
                 result.latitude or 0, result.longitude or 0)
        return {"result": result, "elapsed_ms": elapsed_ms, "error": None}
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        log.error("  [GEO] ✗ FAILED %dms — %s", elapsed_ms, e)
        return {
            "result": GeocodingResult(address_status="unknown"),
            "elapsed_ms": elapsed_ms,
            "error": str(e),
        }


async def process_ticket(
    db: AsyncSession,
    ticket: Ticket,
    batch_id: uuid.UUID | None = None,
) -> dict:
    """
    Process a single ticket through the full AI enrichment pipeline.
    """
    ticket_start = time.time()
    row = ticket.csv_row_index
    desc_preview = (ticket.description or "")[:80].replace("\n", " ")
    log.info("━" * 70)
    log.info("TICKET row=%s id=%s", row, ticket.id)
    log.info("  text: %.80s%s", desc_preview, "…" if len(ticket.description or "") > 80 else "")
    log.info("  addr: %s / %s / %s / %s / %s",
             ticket.country, ticket.region, ticket.city, ticket.street, ticket.house)
    log.info("  age=%s, segment=%s, attachments=%s",
             ticket.age, ticket.segment, ticket.attachments)

    result = {
        "ticket_id": str(ticket.id),
        "csv_row_index": ticket.csv_row_index,
        "stages": {},
    }

    # ── Step 1: Spam pre-filter (T4) ──
    log.info("  [T4 SPAM] checking...")
    spam_result = await check_spam(db, ticket, batch_id)
    result["stages"]["spam_filter"] = {
        "is_spam": spam_result.is_spam,
        "probability": spam_result.probability,
    }
    log.info("  [T4 SPAM] is_spam=%s (prob=%.2f) reason=%s",
             spam_result.is_spam, spam_result.probability, spam_result.reason)

    if spam_result.is_spam:
        ticket.status = TicketStatusEnum.enriched
        await db.flush()
        result["skipped_llm"] = True
        log.info("  ⏭ SPAM — skipping LLM/GEO pipeline")
        log.info("  DONE row=%s in %dms (spam)", row, int((time.time() - ticket_start) * 1000))
        return result

    # ── Step 2: PII anonymization (T3) ──
    log.info("  [T3 PII] anonymizing...")
    pii_result = await anonymize_ticket(db, ticket, batch_id)
    result["stages"]["pii"] = {
        "entities_found": len(pii_result.detections),
    }
    if pii_result.detections:
        for det in pii_result.detections:
            log.info("  [T3 PII]   %s → %s", det.pii_type, det.token)
    else:
        log.info("  [T3 PII]   no PII found")
    await db.flush()

    # ── Step 3: Parallel — LLM (T5) ‖ Sentiment (T6) ‖ Geocoding (T7) ──
    text = ticket.description_anonymized or ticket.description or ""
    log.info("  [PARALLEL] launching LLM + Sentiment + Geocoding...")

    llm_data, sentiment_data, geo_data = await asyncio.gather(
        _run_llm(text, ticket.age, ticket.attachments),
        _run_sentiment(text),
        _run_geocode(ticket.country, ticket.region, ticket.city,
                     ticket.street, ticket.house),
        return_exceptions=True,
    )

    log.info("  [PARALLEL] all three done")

    # Handle exceptions from gather itself
    if isinstance(llm_data, Exception):
        log.error("  [PARALLEL] LLM gather exception: %s", llm_data)
        llm_data = {"result": None, "elapsed_ms": 0, "error": str(llm_data)}
    if isinstance(sentiment_data, Exception):
        log.error("  [PARALLEL] SENTIMENT gather exception: %s", sentiment_data)
        sentiment_data = {"result": SentimentResult(sentiment="нейтральный", confidence=0.0), "elapsed_ms": 0, "error": str(sentiment_data)}
    if isinstance(geo_data, Exception):
        log.error("  [PARALLEL] GEO gather exception: %s", geo_data)
        geo_data = {"result": None, "elapsed_ms": 0, "error": str(geo_data)}

    # ── Step 4: Store results back to main session ──

    # Get or create AI analysis record
    ai_result = await db.execute(
        select(AIAnalysis).where(AIAnalysis.ticket_id == ticket.id)
    )
    ai = ai_result.scalar_one_or_none()
    if not ai:
        ai = AIAnalysis(ticket_id=ticket.id)
        db.add(ai)

    # LLM results (type + language + summary, no sentiment)
    llm_result = llm_data["result"]
    if llm_result:
        ai.detected_type = llm_result.detected_type
        ai.language_label = llm_result.language_label
        ai.language_actual = llm_result.language_actual
        ai.language_is_mixed = llm_result.language_is_mixed
        ai.language_note = llm_result.language_note
        ai.summary = llm_result.summary
        ai.summary_anonymized = llm_result.summary
        ai.attachment_analysis = llm_result.attachment_analysis
        ai.needs_data_change = llm_result.needs_data_change
        ai.needs_location_routing = llm_result.needs_location_routing
        from app.core.config import get_settings
        ai.llm_model = get_settings().OPENROUTER_MODEL
        ai.processing_time_ms = llm_data["elapsed_ms"]
        ticket.ticket_type = llm_result.detected_type
        result["stages"]["llm"] = {
            "type": llm_result.detected_type,
            "language": llm_result.language_label,
            "needs_data_change": llm_result.needs_data_change,
            "needs_location_routing": llm_result.needs_location_routing,
            "elapsed_ms": llm_data["elapsed_ms"],
            "error": llm_data.get("error"),
        }
    else:
        result["stages"]["llm"] = {"error": llm_data.get("error", "Unknown error")}

    # Sentiment results (separate T6 call)
    sentiment_result = sentiment_data["result"]
    if sentiment_result:
        ai.sentiment = sentiment_result.sentiment
        ai.sentiment_confidence = sentiment_result.confidence
        result["stages"]["sentiment"] = {
            "sentiment": sentiment_result.sentiment,
            "confidence": sentiment_result.confidence,
            "elapsed_ms": sentiment_data["elapsed_ms"],
            "error": sentiment_data.get("error"),
        }
    else:
        ai.sentiment = "нейтральный"
        ai.sentiment_confidence = 0.0
        result["stages"]["sentiment"] = {"error": sentiment_data.get("error", "Unknown error")}

    # Geocoding results
    geo_result = geo_data["result"]
    if geo_result:
        ticket.latitude = geo_result.latitude
        ticket.longitude = geo_result.longitude
        ticket.address_status = geo_result.address_status
        ticket.geo_explanation = geo_result.explanation
        if geo_result.latitude and geo_result.longitude:
            ticket.geo_point = f"SRID=4326;POINT({geo_result.longitude} {geo_result.latitude})"
        result["stages"]["geocoding"] = {
            "lat": geo_result.latitude,
            "lon": geo_result.longitude,
            "provider": geo_result.provider,
            "status": geo_result.address_status,
            "geo_explanation": geo_result.explanation,
            "elapsed_ms": geo_data["elapsed_ms"],
            "error": geo_data.get("error"),
        }
    else:
        result["stages"]["geocoding"] = {"error": geo_data.get("error", "Unknown error")}

    # Store processing states for LLM, sentiment, and geocoding
    for stage_name, data, stage_enum in [
        ("llm_analysis", llm_data, ProcessingStageEnum.llm_analysis),
        ("sentiment_analysis", sentiment_data, ProcessingStageEnum.sentiment_analysis),
        ("geocoding", geo_data, ProcessingStageEnum.geocoding),
    ]:
        proc = ProcessingState(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage=stage_enum,
            status=StageStatusEnum.completed if not data.get("error") else StageStatusEnum.failed,
            progress_pct=100.0,
            message=f"{stage_name} {'completed' if not data.get('error') else 'failed'} ({data['elapsed_ms']}ms)",
            error_detail=data.get("error"),
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
        db.add(proc)

    # ── Step 5: PII re-hydration ──
    if ai.summary:
        pii_maps = await db.execute(
            select(PIIMapping).where(PIIMapping.ticket_id == ticket.id)
        )
        mappings = [
            {
                "token": m.token,
                "original": m.original_value.decode("utf-8") if isinstance(m.original_value, bytes) else m.original_value,
            }
            for m in pii_maps.scalars().all()
        ]
        if mappings:
            log.info("  [REHYDRATE] replacing %d PII tokens in summary", len(mappings))
            ai.summary = rehydrate_text(ai.summary, mappings)
        else:
            log.info("  [REHYDRATE] no PII tokens to replace")

    # ── Step 6: Mark ticket as enriched ──
    ticket.status = TicketStatusEnum.enriched
    await db.flush()

    # ── Step 7: Location-based routing (assign to nearest office / manager) ──
    assignment = await assign_ticket_to_nearest(ticket, db, batch_id)
    if assignment:
        result["stages"]["routing"] = {
            "assigned_manager_id": str(assignment.manager_id),
            "business_unit_id": str(assignment.business_unit_id) if assignment.business_unit_id else None,
            "distance_km": assignment.routing_details.get("distance_km"),
            "office_name": assignment.routing_details.get("office_name"),
        }
        await sse_manager.send_update(
            ticket_id=ticket.id,
            batch_id=batch_id,
            stage="routing",
            status="completed",
            field="assignment",
            data=result["stages"]["routing"],
        )
    else:
        result["stages"]["routing"] = {"error": "No candidate managers"}
        ticket.status = TicketStatusEnum.enriched  # leave as enriched if no assignment

    await db.flush()
    elapsed_total = int((time.time() - ticket_start) * 1000)
    log.info("  DONE row=%s in %dms — type=%s, sentiment=%s, geo=%s, routed=%s",
             row, elapsed_total, ai.detected_type, ai.sentiment,
             ticket.address_status, bool(assignment))

    # SSE: ticket fully enriched (and routed if assignment succeeded)
    await sse_manager.send_update(
        ticket_id=ticket.id,
        batch_id=batch_id,
        stage="enrichment",
        status="completed",
        message="All AI analysis complete" + ("; assigned to manager" if assignment else ""),
        data=result["stages"],
    )

    return result


async def process_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
) -> dict:
    """
    Process all tickets in a batch through the AI enrichment pipeline.
    Tickets are processed sequentially (each ticket has parallel internal calls).
    """
    batch_result = await db.execute(
        select(BatchUpload).where(BatchUpload.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    tickets_result = await db.execute(
        select(Ticket)
        .join(ProcessingState, ProcessingState.ticket_id == Ticket.id)
        .where(
            ProcessingState.batch_id == batch_id,
            ProcessingState.stage == ProcessingStageEnum.ingestion,
            ProcessingState.status == StageStatusEnum.completed,
        )
        .order_by(Ticket.csv_row_index)
    )
    tickets = tickets_result.scalars().all()

    if not tickets:
        log.warning("BATCH %s — no tickets found", batch_id)
        return {"batch_id": str(batch_id), "processed": 0, "message": "No tickets found"}

    log.info("=" * 70)
    log.info("BATCH START — %s — %d tickets", batch_id, len(tickets))
    log.info("=" * 70)

    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="pipeline",
        status="in_progress",
        message=f"Processing {len(tickets)} tickets",
        data={"total": len(tickets)},
    )

    batch_start = time.time()
    results = []
    for i, ticket in enumerate(tickets):
        log.info("[%d/%d] Processing ticket row=%s...", i + 1, len(tickets), ticket.csv_row_index)
        try:
            ticket_result = await process_ticket(db, ticket, batch_id)
            results.append(ticket_result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            log.error("[%d/%d] EXCEPTION for row=%s: %s", i + 1, len(tickets), ticket.csv_row_index, e)
            results.append({
                "ticket_id": str(ticket.id),
                "error": str(e),
            })

        # Commit after each ticket
        await db.commit()

    batch_elapsed = int((time.time() - batch_start) * 1000)
    spam_count = sum(1 for r in results if r.get("skipped_llm"))
    error_count = sum(1 for r in results if r.get("error"))
    log.info("=" * 70)
    log.info("BATCH DONE — %d tickets in %dms (spam=%d, enriched=%d, errors=%d)",
             len(results), batch_elapsed, spam_count,
             len(results) - spam_count - error_count, error_count)
    log.info("=" * 70)
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="pipeline",
        status="completed",
        message=f"Batch processing complete: {len(results)} tickets ({spam_count} spam)",
        data={
            "total": len(results),
            "spam": spam_count,
            "enriched": len(results) - spam_count,
        },
    )

    return {
        "batch_id": str(batch_id),
        "processed": len(results),
        "spam_filtered": spam_count,
        "enriched": len(results) - spam_count,
    }
