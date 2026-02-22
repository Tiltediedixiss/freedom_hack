"""
In-memory progress store for pipeline batches.
Updated by the pipeline; polled by the frontend when SSE is unreliable.
"""

_batch_progress: dict[str, dict] = {}


def set_progress(batch_id: str, total: int, processed: int, spam: int, current: int, status: str = "processing"):
    entry = _batch_progress.get(batch_id) or {}
    _batch_progress[batch_id] = {
        "total": total,
        "processed": processed,
        "spam": spam,
        "current": current,
        "status": status,
        "results": entry.get("results", []),
    }


def add_result(
    batch_id: str,
    ticket_id: str,
    csv_row: int | None,
    type_: str | None,
    sentiment: str | None,
    summary: str | None,
    latitude: float | None,
    longitude: float | None,
    is_spam: bool,
    geo_filter: dict | None = None,
    skills_filter: dict | None = None,
    priority: dict | None = None,
):
    entry = _batch_progress.get(batch_id)
    if not entry:
        return
    results = entry.get("results", [])
    results.append({
        "ticket_id": ticket_id,
        "csv_row": csv_row,
        "type": type_ or "—",
        "sentiment": sentiment or "—",
        "summary": summary or "—",
        "latitude": latitude,
        "longitude": longitude,
        "is_spam": is_spam,
        "is_complete": True,
        "geo_filter": geo_filter,
        "skills_filter": skills_filter,
        "priority": priority,
    })
    entry["results"] = results


def get_progress(batch_id: str) -> dict | None:
    return _batch_progress.get(batch_id)
