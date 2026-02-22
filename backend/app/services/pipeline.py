import asyncio
import logging
import time

from app.services.csv_parser import parse_tickets, parse_managers, parse_business_units
from app.services.personal_data_masking import anonymize_ticket, rehydrate_ticket
from app.services.spam_prefiltering import check_spam_ticket
from app.services.llm_processing import analyze_ticket as llm_analyze, analyze_batch as llm_batch
from app.services.geocoder import geocode_ticket, geocode_batch
from app.services.priority import score_batch
from app.services.routing import route_batch

log = logging.getLogger("fire.pipeline")


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