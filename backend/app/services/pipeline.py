import asyncio
import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AIAnalysis,
    BatchUpload,
    Ticket,
    TicketTypeEnum,
    SentimentEnum,
    TicketStatusEnum,
)
from app.services.csv_parser import parse_tickets, parse_managers, parse_business_units
from app.services.personal_data_masking import anonymize_ticket, rehydrate_ticket
from app.services.spam_prefiltering import check_spam_ticket, check_spam
from app.services.llm_processing import analyze_ticket as llm_analyze, analyze_batch as llm_batch
from app.services.geocoder import geocode_ticket, geocode_batch
from app.services.priority import score_batch, compute_priority
from collections import Counter
from app.services.routing import route_batch
from app.services.geo_filtering import assign_ticket_to_nearest
from app.core.sse_manager import sse_manager
from app.core.progress_store import set_progress, add_result

log = logging.getLogger("fire.pipeline")

# LLM type string -> TicketTypeEnum
_LLM_TYPE_TO_ENUM = {
    "жалоба": TicketTypeEnum.жалоба,
    "смена данных": TicketTypeEnum.смена_данных,
    "консультация": TicketTypeEnum.консультация,
    "претензия": TicketTypeEnum.претензия,
    "неработоспособность приложения": TicketTypeEnum.неработоспособность,
    "мошеннические действия": TicketTypeEnum.мошенничество,
    "спам": TicketTypeEnum.спам,
}
_SENTIMENT_TO_ENUM = {
    "негативный": SentimentEnum.негативный,
    "нейтральный": SentimentEnum.нейтральный,
    "позитивный": SentimentEnum.позитивный,
}


async def process_batch(db: AsyncSession, batch_id: uuid.UUID) -> dict:
    """
    Run the enrichment pipeline for all tickets in a batch (DB mode).
    Loads batch and tickets (heuristic: most recent ingested up to batch.total_rows), then
    for each ticket: spam check -> PII anonymize -> LLM + geocode -> routing.
    """
    t0 = time.perf_counter()
    log.info("[PIPELINE] process_batch start: batch_id=%s", batch_id)

    result = await db.execute(select(BatchUpload).where(BatchUpload.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        log.warning("[PIPELINE] batch not found: %s", batch_id)
        return {"error": "Batch not found", "processed": 0}

    result = await db.execute(
        select(Ticket)
        .where(Ticket.status == TicketStatusEnum.ingested)
        .order_by(Ticket.created_at.desc())
        .limit(max(1, batch.total_rows or 0))
    )
    tickets = list(result.scalars().all())
    if not tickets:
        log.warning("[PIPELINE] no ingested tickets for batch %s", batch_id)
        return {"message": "No ingested tickets to process", "processed": 0}

    log.info("[PIPELINE] loaded %d tickets, sending pipeline in_progress", len(tickets))
    batch_id_str = str(batch_id)
    set_progress(batch_id_str, len(tickets), 0, 0, 1, "processing")
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="pipeline",
        status="in_progress",
        message=f"Обработка {len(tickets)} обращений",
        data={"total": len(tickets), "processed": 0, "spam": 0, "current": 1},
    )

    processed = 0
    spam_count = 0
    guids = [t.guid for t in tickets if t.guid]
    guid_counts = dict(Counter(guids))
    for idx, ticket in enumerate(tickets):
        current = idx + 1
        log.info("[PIPELINE] ticket %d/%d: %s", current, len(tickets), ticket.id)
        set_progress(batch_id_str, len(tickets), processed, spam_count, current, "processing")
        await sse_manager.send_update(
            ticket_id=uuid.UUID(int=0),
            batch_id=batch_id,
            stage="pipeline",
            status="in_progress",
            message=f"Обработка {current}/{len(tickets)}",
            data={"total": len(tickets), "processed": processed, "spam": spam_count, "current": current},
        )
        try:
            spam_result = await check_spam(db, ticket, str(batch_id))
            if spam_result.is_spam:
                spam_count += 1
                ticket.status = TicketStatusEnum.enriched
                await db.flush()
                await sse_manager.send_update(
                    ticket_id=ticket.id,
                    batch_id=batch_id,
                    stage="spam_filter",
                    status="completed",
                    message="Спам обнаружен",
                    data={
                        "is_spam": True,
                        "reason": getattr(spam_result, "reason", None),
                        "csv_row_index": getattr(ticket, "csv_row_index", None),
                    },
                )
                await sse_manager.send_update(
                    ticket_id=ticket.id,
                    batch_id=batch_id,
                    stage="enrichment",
                    status="completed",
                    message="Пропущен (спам)",
                    data={"skipped": True, "is_spam": True},
                )
                add_result(
                    batch_id_str,
                    str(ticket.id),
                    getattr(ticket, "csv_row_index", None),
                    None,
                    None,
                    None,
                    None,
                    None,
                    is_spam=True,
                )
                processed += 1
                set_progress(batch_id_str, len(tickets), processed, spam_count, current, "processing")
                continue

            await anonymize_ticket(db, ticket, batch_id)
            await db.flush()

            t_dict = {
                "description": ticket.description,
                "description_anonymized": ticket.description_anonymized,
                "age": ticket.age,
                "segment": getattr(ticket.segment, "name", None) if ticket.segment else None,
                "attachments": ticket.attachments or [],
                "country": ticket.country,
                "region": ticket.region,
                "city": ticket.city,
                "street": ticket.street,
                "house": ticket.house,
            }
            llm_result, geo_result = await asyncio.gather(
                llm_analyze(t_dict),
                geocode_ticket(dict(t_dict)),
                return_exceptions=True,
            )
            llm_data = {}
            if isinstance(llm_result, Exception):
                log.warning("LLM failed for ticket %s: %s", ticket.id, llm_result)
                llm_data = {"error": str(llm_result), "type": "Консультация", "sentiment": "Нейтральный"}
            else:
                type_str = (llm_result.get("type") or "Консультация").strip().lower()
                sentiment_str = (llm_result.get("sentiment") or "Нейтральный").strip().lower()
                llm_data = {
                    "type": llm_result.get("type") or "Консультация",
                    "sentiment": llm_result.get("sentiment") or "Нейтральный",
                    "summary": llm_result.get("summary"),
                    "sentiment_confidence": float(llm_result.get("sentiment_confidence", 0.5)),
                }
                ai = AIAnalysis(
                    ticket_id=ticket.id,
                    detected_type=_LLM_TYPE_TO_ENUM.get(type_str, TicketTypeEnum.консультация),
                    summary=llm_result.get("summary"),
                    sentiment=_SENTIMENT_TO_ENUM.get(sentiment_str, SentimentEnum.нейтральный),
                    sentiment_confidence=float(llm_result.get("sentiment_confidence", 0.5)),
                    language_label=llm_result.get("language_label", "RU"),
                )
                db.add(ai)
            await sse_manager.send_update(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage="llm_analysis",
                status="completed",
                message="Анализ выполнен",
                data=llm_data,
            )

            geo_data = {}
            if isinstance(geo_result, Exception):
                log.warning("Geocode failed for ticket %s: %s", ticket.id, geo_result)
                geo_data = {"error": str(geo_result)}
            else:
                ticket.latitude = geo_result.get("latitude")
                ticket.longitude = geo_result.get("longitude")
                ticket.geo_explanation = geo_result.get("geo_explanation")
                geo_data = {
                    "latitude": geo_result.get("latitude"),
                    "longitude": geo_result.get("longitude"),
                    "geo_explanation": geo_result.get("geo_explanation"),
                }
            await sse_manager.send_update(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage="geocoding",
                status="completed",
                message="Геокодирование выполнено" if not isinstance(geo_result, Exception) else "Ошибка геокодирования",
                data=geo_data,
            )

            ticket.status = TicketStatusEnum.enriched
            segment_name = getattr(ticket.segment, "name", None) or "Mass"
            ticket_type_str = llm_data.get("type") or "Консультация"
            language_label = llm_result.get("language_label", "RU") if not isinstance(llm_result, Exception) else "RU"
            _, geo_info, skills_info = await assign_ticket_to_nearest(
                ticket, db, str(batch_id),
                segment=segment_name,
                ticket_type=ticket_type_str,
                language_label=language_label,
            )
            priority_breakdown = compute_priority(
                segment=segment_name,
                ticket_type=ticket_type_str,
                sentiment=llm_data.get("sentiment") or "Нейтральный",
                age=ticket.age,
                country=ticket.country,
                csv_row_index=ticket.csv_row_index or idx,
                total_rows=len(tickets),
                guid_counts=guid_counts,
                guid=ticket.guid or "",
            )
            await db.flush()
            await sse_manager.send_update(
                ticket_id=ticket.id,
                batch_id=batch_id,
                stage="enrichment",
                status="completed",
                message="Обогащение завершено",
                data={
                    "type": llm_data.get("type"),
                    "sentiment": llm_data.get("sentiment"),
                    "summary": llm_data.get("summary"),
                    "latitude": geo_data.get("latitude"),
                    "longitude": geo_data.get("longitude"),
                },
            )
            add_result(
                batch_id_str,
                str(ticket.id),
                getattr(ticket, "csv_row_index", None),
                llm_data.get("type"),
                llm_data.get("sentiment"),
                llm_data.get("summary"),
                geo_data.get("latitude"),
                geo_data.get("longitude"),
                is_spam=False,
                geo_filter=geo_info,
                skills_filter=skills_info,
                priority=priority_breakdown,
            )
            processed += 1
            set_progress(batch_id_str, len(tickets), processed, spam_count, current, "processing")
        except Exception as e:
            log.exception("Pipeline failed for ticket %s: %s", ticket.id, e)

    elapsed = time.perf_counter() - t0
    log.info("[PIPELINE] done in %.1fs: processed=%d, spam=%d", elapsed, processed, spam_count)
    set_progress(batch_id_str, len(tickets), processed, spam_count, len(tickets), "completed")
    await sse_manager.send_update(
        ticket_id=uuid.UUID(int=0),
        batch_id=batch_id,
        stage="pipeline",
        status="completed",
        message=f"Обработано {processed} из {len(tickets)}",
        data={"total": len(tickets), "processed": processed, "spam": spam_count, "enriched": processed - spam_count},
    )
    return {"processed": processed, "total": len(tickets)}


async def process_ticket(ticket: dict, uploads_dir: str = "/app/uploads") -> dict:
    ticket_start = time.time()
    row = ticket.get("csv_row_index", "?")

    anonymize_ticket(ticket)

    check_spam_ticket(ticket)
    if ticket.get("is_spam"):
        ticket["total_latency_ms"] = int((time.time() - ticket_start) * 1000)
        log.info("row=%s SPAM (%dms): %s", row, ticket["total_latency_ms"], ticket.get("spam_reason"))
        return ticket

    llm_result, geo_result = await asyncio.gather(
        llm_analyze(ticket, uploads_dir),
        geocode_ticket(ticket),
        return_exceptions=True,
    )

    if isinstance(llm_result, Exception):
        log.error("row=%s LLM failed: %s", row, llm_result)
        ticket["type"] = ticket.get("type") or "Консультация"
        ticket["sentiment"] = "Нейтральный"
        ticket["explanation"] = f"Ошибка LLM: {llm_result}"
    if isinstance(geo_result, Exception):
        log.error("row=%s GEO failed: %s", row, geo_result)
        ticket["latitude"] = None
        ticket["longitude"] = None
        ticket["geo_explanation"] = f"Ошибка геокодирования: {geo_result}"

    rehydrate_ticket(ticket)

    ticket["total_latency_ms"] = int((time.time() - ticket_start) * 1000)
    log.info(
        "row=%s done (%dms): type=%s sentiment=%s lang=%s geo=%s",
        row, ticket["total_latency_ms"],
        ticket.get("type"), ticket.get("sentiment"),
        ticket.get("language_label"), ticket.get("geo_provider"),
    )
    return ticket


async def run_pipeline(
    tickets_path: str,
    managers_path: str,
    business_units_path: str,
    uploads_dir: str = "/app/uploads",
    llm_concurrency: int = 5,
) -> dict:
    pipeline_start = time.time()

    log.info("=" * 60)
    log.info("PIPELINE START")
    log.info("=" * 60)

    tickets = parse_tickets(tickets_path)
    managers = parse_managers(managers_path)
    business_units = parse_business_units(business_units_path)
    log.info("Parsed: %d tickets, %d managers, %d offices", len(tickets), len(managers), len(business_units))

    for t in tickets:
        anonymize_ticket(t)

    spam_count = 0
    for t in tickets:
        check_spam_ticket(t)
        if t.get("is_spam"):
            spam_count += 1

    non_spam = [t for t in tickets if not t.get("is_spam")]
    log.info("Spam filtered: %d spam, %d to process", spam_count, len(non_spam))

    if non_spam:
        sem = asyncio.Semaphore(llm_concurrency)

        async def _llm_with_sem(t: dict) -> dict:
            async with sem:
                try:
                    return await llm_analyze(t, uploads_dir)
                except Exception as e:
                    log.error("row=%s LLM failed: %s", t.get("csv_row_index"), e)
                    t["type"] = t.get("type") or "Консультация"
                    t["sentiment"] = "Нейтральный"
                    t["explanation"] = f"Ошибка LLM: {e}"
                    return t

        async def _geo_with_sem(t: dict) -> dict:
            async with sem:
                try:
                    return await geocode_ticket(t)
                except Exception as e:
                    log.error("row=%s GEO failed: %s", t.get("csv_row_index"), e)
                    t["latitude"] = None
                    t["longitude"] = None
                    t["geo_explanation"] = f"Ошибка: {e}"
                    return t

        llm_tasks = [_llm_with_sem(t) for t in non_spam]
        geo_tasks = [_geo_with_sem(t) for t in non_spam]

        await asyncio.gather(*llm_tasks, *geo_tasks)

        for t in non_spam:
            rehydrate_ticket(t)

    log.info("LLM + geocoding done for %d tickets", len(non_spam))

    scored = score_batch(tickets)
    for s in scored:
        idx = s["csv_row_index"]
        for t in tickets:
            if t["csv_row_index"] == idx:
                t["priority"] = s["priority"]
                break

    log.info("Priority scoring done")

    assignments = route_batch(tickets, managers)
    assignment_map = {a["csv_row_index"]: a for a in assignments}
    for t in tickets:
        a = assignment_map.get(t["csv_row_index"])
        if a:
            t["assigned_manager_id"] = a.get("manager_id")
            t["assigned_manager_name"] = a.get("manager_name")
            t["assigned_office"] = a.get("office")
            t["routing_explanation"] = a.get("explanation")
            t["routing_skipped"] = a.get("skipped", False)

    routed_count = sum(1 for a in assignments if a.get("manager_id"))
    unrouted_count = sum(1 for a in assignments if not a.get("manager_id") and not a.get("skipped"))
    log.info("Routing done: %d assigned, %d unrouted, %d skipped (spam)", routed_count, unrouted_count, spam_count)

    elapsed = int((time.time() - pipeline_start) * 1000)
    log.info("=" * 60)
    log.info("PIPELINE DONE in %dms — %d tickets (%d spam, %d routed, %d unrouted)",
             elapsed, len(tickets), spam_count, routed_count, unrouted_count)
    log.info("=" * 60)

    return {
        "total_tickets": len(tickets),
        "spam_filtered": spam_count,
        "enriched": len(non_spam),
        "routed": routed_count,
        "unrouted": unrouted_count,
        "elapsed_ms": elapsed,
        "tickets": tickets,
        "assignments": assignments,
        "managers": managers,
    }