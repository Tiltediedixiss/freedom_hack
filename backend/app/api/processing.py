"""
API routes for SSE streaming and pipeline control.
  GET  /api/processing/stream           — SSE endpoint
  POST /api/processing/start/{batch_id} — trigger pipeline for batch
  GET  /api/processing/status/{batch_id} — get processing states
"""

import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db, async_session_factory
from app.core.sse_manager import sse_manager
from app.models.models import BatchUpload, ProcessingState
from app.models.schemas import ProcessingStateResponse
from app.services.pipeline import process_batch

router = APIRouter(prefix="/api/processing", tags=["Processing"])


@router.get("/stream")
async def sse_stream():
    """SSE stream for real-time frontend updates."""
    subscriber_id = sse_manager.subscribe()

    async def event_generator():
        try:
            async for data in sse_manager.stream(subscriber_id):
                yield data
        except asyncio.CancelledError:
            sse_manager.unsubscribe(subscriber_id)
        except Exception:
            sse_manager.unsubscribe(subscriber_id)

    return EventSourceResponse(event_generator())


@router.post("/start/{batch_id}")
async def start_processing(
    batch_id: uuid.UUID,
    background_tasks: BackgroundTasks,
):
    """
    Trigger the AI enrichment pipeline for a batch of tickets.
    Runs in the background so the API returns immediately.
    SSE provides real-time progress updates.
    """
    async def _run_pipeline():
        async with async_session_factory() as db:
            try:
                result = await process_batch(db, batch_id)
                await db.commit()
            except Exception as e:
                import traceback
                traceback.print_exc()
                await db.rollback()
                await sse_manager.send_update(
                    ticket_id=uuid.UUID(int=0),
                    batch_id=batch_id,
                    stage="pipeline",
                    status="failed",
                    message=f"Pipeline error: {str(e)}",
                )

    background_tasks.add_task(_run_pipeline)

    return {
        "message": f"Processing started for batch {batch_id}",
        "batch_id": str(batch_id),
        "stream_url": "/api/processing/stream",
    }


@router.get("/status/{batch_id}", response_model=list[ProcessingStateResponse])
async def get_processing_status(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProcessingState)
        .where(ProcessingState.batch_id == batch_id)
        .order_by(ProcessingState.created_at)
    )
    return [ProcessingStateResponse.model_validate(s) for s in result.scalars().all()]
