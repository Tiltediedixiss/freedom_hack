"""
API routes for ticket CRUD operations.
  GET  /api/tickets           — list tickets (paginated)
  GET  /api/tickets/{id}      — get single ticket
  GET  /api/tickets/safe      — PII-stripped list
  GET  /api/tickets/batch/{id} — get batch status
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import BatchUpload, Ticket
from app.models.schemas import (
    BatchUploadResponse,
    TicketResponse,
    TicketSafeResponse,
)

router = APIRouter(prefix="/api/tickets", tags=["Tickets"])


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    is_spam: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """List tickets with optional filters and pagination."""
    query = select(Ticket).order_by(Ticket.created_at.desc())

    if status:
        query = query.where(Ticket.status == status)
    if is_spam is not None:
        query = query.where(Ticket.is_spam == is_spam)

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tickets = result.scalars().all()

    return [TicketResponse.model_validate(t) for t in tickets]


@router.get("/count")
async def ticket_count(
    status: Optional[str] = None,
    is_spam: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get total ticket count with optional filters."""
    query = select(func.count(Ticket.id))
    if status:
        query = query.where(Ticket.status == status)
    if is_spam is not None:
        query = query.where(Ticket.is_spam == is_spam)
    result = await db.execute(query)
    return {"count": result.scalar()}


@router.get("/batch/{batch_id}", response_model=BatchUploadResponse)
async def get_batch_status(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the status of a batch upload."""
    result = await db.execute(
        select(BatchUpload).where(BatchUpload.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchUploadResponse.model_validate(batch)


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single ticket by ID."""
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return TicketResponse.model_validate(ticket)
