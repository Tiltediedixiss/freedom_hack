"""
In-memory progress store for pipeline batches.
Updated by the pipeline; polled by the frontend when SSE is unreliable.
"""

_batch_progress: dict[str, dict] = {}


def set_progress(batch_id: str, total: int, processed: int, spam: int, current: int, status: str = "processing"):
    _batch_progress[batch_id] = {
        "total": total,
        "processed": processed,
        "spam": spam,
        "current": current,
        "status": status,
    }


def get_progress(batch_id: str) -> dict | None:
    return _batch_progress.get(batch_id)
