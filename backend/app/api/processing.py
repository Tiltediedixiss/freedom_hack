"""
API routes for SSE streaming and processing control.
  GET  /api/processing/stream    — SSE endpoint for real-time updates
  POST /api/processing/start     — trigger processing pipeline for a batch
  GET  /api/processing/status/{batch_id} — get processing status
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.core.sse_manager import sse_manager
from app.models.models import ProcessingState
from app.models.schemas import ProcessingStateResponse

router = APIRouter(prefix="/api/processing", tags=["Processing"])


@router.get("/stream")
async def sse_stream():
    """
    Server-Sent Events stream.
    Frontend connects here to receive real-time processing updates.
    """
    subscriber_id = sse_manager.subscribe()

    async def event_generator():
        try:
            async for data in sse_manager.stream(subscriber_id):
                yield data
        except Exception:
            sse_manager.unsubscribe(subscriber_id)

    return EventSourceResponse(event_generator())


@router.get("/status/{batch_id}", response_model=list[ProcessingStateResponse])
async def get_processing_status(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all processing states for a given batch."""
    result = await db.execute(
        select(ProcessingState)
        .where(ProcessingState.batch_id == batch_id)
        .order_by(ProcessingState.created_at)
    )
    states = result.scalars().all()
    return [ProcessingStateResponse.model_validate(s) for s in states]
