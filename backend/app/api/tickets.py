"""
API routes for ticket operations.
  GET  /api/tickets            — list all tickets (paginated)
  GET  /api/tickets/count      — total ticket count
  GET  /api/tickets/export     — export results.json (full text + sentiment)
  GET  /api/tickets/batch/{id} — batch upload status
  GET  /api/tickets/row/{idx}  — lookup by CSV row index (demo feature)
  GET  /api/tickets/{id}       — single ticket by UUID
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.services.routing import get_candidate_managers
from app.models.models import (
    AIAnalysis, Assignment, BatchUpload, BusinessUnit,
    Manager, PIIMapping, Ticket,
)
from app.models.schemas import (
    AIAnalysisResponse, AssignmentResponse, BatchUploadResponse,
    BusinessUnitResponse, ManagerCandidateResponse, ManagerResponse,
    TicketLookupResponse, TicketResponse,
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
    query = select(Ticket).order_by(Ticket.csv_row_index)
    if status:
        query = query.where(Ticket.status == status)
    if is_spam is not None:
        query = query.where(Ticket.is_spam == is_spam)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return [TicketResponse.model_validate(t) for t in result.scalars().all()]


@router.get("/count")
async def ticket_count(
    status: Optional[str] = None,
    is_spam: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(func.count(Ticket.id))
    if status:
        query = query.where(Ticket.status == status)
    if is_spam is not None:
        query = query.where(Ticket.is_spam == is_spam)
    result = await db.execute(query)
    return {"count": result.scalar()}


@router.get("/export")
async def export_results(
    batch_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all enriched tickets as results.json.
    Returns full description text (not truncated preview),
    separate sentiment analysis result, and PII count.
    """
    query = (
        select(Ticket)
        .options(
            selectinload(Ticket.ai_analysis),
            selectinload(Ticket.pii_mappings),
        )
        .order_by(Ticket.csv_row_index)
    )
    result = await db.execute(query)
    tickets = result.scalars().all()

    export_data = []
    for t in tickets:
        ai = t.ai_analysis
        pii_count = len(t.pii_mappings) if t.pii_mappings else 0

        entry = {
            "row": t.csv_row_index,
            "guid": t.guid,
            "age": t.age,
            "segment": t.segment,
            "text": t.description,
            "is_spam": t.is_spam,
            "spam_probability": round(t.spam_probability, 4) if t.spam_probability else 0,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "ticket_type": t.ticket_type,
            "address": {
                "country": t.country,
                "region": t.region,
                "city": t.city,
                "street": t.street,
                "house": t.house,
                "lat": t.latitude,
                "lon": t.longitude,
                "geo_status": t.address_status,
                "geo_explanation": t.geo_explanation,
            },
            "ai": None,
            "sentiment": None,
            "pii_count": pii_count,
        }

        if ai:
            entry["ai"] = {
                "type": ai.detected_type,
                "language": ai.language_label,
                "language_actual": ai.language_actual,
                "summary": ai.summary,
                "needs_data_change": ai.needs_data_change,
                "needs_location_routing": ai.needs_location_routing,
                "processing_time_ms": ai.processing_time_ms,
            }
            entry["sentiment"] = {
                "label": ai.sentiment,
                "confidence": round(ai.sentiment_confidence, 4) if ai.sentiment_confidence else None,
            }

        export_data.append(entry)

    return JSONResponse(content=export_data)


@router.get("/batch/{batch_id}", response_model=BatchUploadResponse)
async def get_batch_status(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BatchUpload).where(BatchUpload.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Batch not found")
    return BatchUploadResponse.model_validate(batch)


@router.get("/row/{row_index}", response_model=TicketLookupResponse)
async def lookup_by_row(
    row_index: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Lookup ticket by CSV row index — the key demo feature.
    Returns full assignment chain: ticket + AI analysis + assignment + manager + office.
    """
    result = await db.execute(
        select(Ticket)
        .options(
            selectinload(Ticket.ai_analysis),
            selectinload(Ticket.assignment),
        )
        .where(Ticket.csv_row_index == row_index)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, f"No ticket found for row index {row_index}")

    response = TicketLookupResponse(
        ticket=TicketResponse.model_validate(ticket),
    )

    if ticket.ai_analysis:
        response.ai_analysis = AIAnalysisResponse.model_validate(ticket.ai_analysis)

    if ticket.assignment:
        response.assignment = AssignmentResponse.model_validate(ticket.assignment)

        # Fetch manager
        mgr_result = await db.execute(
            select(Manager).where(Manager.id == ticket.assignment.manager_id)
        )
        mgr = mgr_result.scalar_one_or_none()
        if mgr:
            response.manager = ManagerResponse.model_validate(mgr)
            if mgr.business_unit_id:
                bu_result = await db.execute(
                    select(BusinessUnit).where(BusinessUnit.id == mgr.business_unit_id)
                )
                bu = bu_result.scalar_one_or_none()
                if bu:
                    response.business_unit = BusinessUnitResponse.model_validate(bu)

    return response


@router.get("/{ticket_id}/candidates", response_model=list[ManagerCandidateResponse])
async def get_ticket_candidates(
    ticket_id: uuid.UUID,
    max_km: Optional[float] = Query(500.0, description="Max distance (km) to include office"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get managers that can serve this ticket, sorted by distance (nearest office first).
    Uses ticket coordinates from geocoding and business_unit coordinates (geocoded on ingest).
    """
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    candidates = await get_candidate_managers(ticket, db, max_km=max_km)
    return [
        ManagerCandidateResponse(
            manager=ManagerResponse.model_validate(c.manager),
            business_unit=BusinessUnitResponse.model_validate(c.business_unit) if c.business_unit else None,
            distance_km=c.distance_km if c.distance_km != float("inf") else None,
            office_name=c.office_name,
        )
        for c in candidates
    ]


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return TicketResponse.model_validate(ticket)
