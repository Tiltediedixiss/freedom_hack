"""
T10 — Location-based routing: assign tickets to managers by distance.

Uses ticket coordinates (from T7 geocoder) and business_unit coordinates
(geocoded on ingest) to:
  1. Compute distance from ticket to each office (Haversine).
  2. Rank managers by distance (nearest office first), then by load (stress_score).
  3. Assign ticket to the best candidate and create Assignment.

Managers are linked to business_units by business_unit_id (office name in CSV).
"""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sse_manager import sse_manager
from app.models.models import (
    Assignment, BusinessUnit, Manager, Ticket,
    TicketStatusEnum,
)

log = logging.getLogger("pipeline.routing")

# Earth radius in km for Haversine
EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Distance between two (lat, lon) points in km (Haversine)."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


@dataclass
class ManagerCandidate:
    """Manager with distance to ticket and office info."""
    manager: Manager
    business_unit: BusinessUnit | None
    distance_km: float
    office_name: str | None


async def get_candidate_managers(
    ticket: Ticket,
    db: AsyncSession,
    max_km: float | None = 500.0,
) -> list[ManagerCandidate]:
    """
    Get managers that can serve this ticket, sorted by distance (nearest office first).
    Only includes managers whose office has coordinates; ticket must have coordinates too.
    """
    if ticket.latitude is None or ticket.longitude is None:
        log.info("  [ROUTING] ticket has no coords — skipping distance filter")
        # Return all managers with office, sorted by load (no distance)
        result = await db.execute(
            select(Manager, BusinessUnit)
            .outerjoin(BusinessUnit, Manager.business_unit_id == BusinessUnit.id)
            .where(Manager.is_active == True)
            .order_by(Manager.stress_score.asc())
        )
        rows = result.all()
        return [
            ManagerCandidate(
                manager=m,
                business_unit=bu,
                distance_km=float("inf") if bu and bu.latitude else 0.0,
                office_name=bu.name if bu else None,
            )
            for m, bu in rows
        ]

    ticket_lat, ticket_lon = float(ticket.latitude), float(ticket.longitude)

    result = await db.execute(
        select(Manager, BusinessUnit)
        .join(BusinessUnit, Manager.business_unit_id == BusinessUnit.id)
        .where(
            Manager.is_active == True,
            BusinessUnit.latitude.isnot(None),
            BusinessUnit.longitude.isnot(None),
        )
    )
    rows = result.all()
    candidates: list[ManagerCandidate] = []
    for manager, bu in rows:
        dist = haversine_km(
            ticket_lat, ticket_lon,
            float(bu.latitude), float(bu.longitude),
        )
        if max_km is not None and dist > max_km:
            continue
        candidates.append(
            ManagerCandidate(
                manager=manager,
                business_unit=bu,
                distance_km=dist,
                office_name=bu.name,
            )
        )

    # Sort by distance, then by stress (load)
    candidates.sort(key=lambda c: (c.distance_km, c.manager.stress_score or 0))
    return candidates


async def assign_ticket_to_nearest(
    ticket: Ticket,
    db: AsyncSession,
    batch_id: uuid.UUID | None = None,
) -> Assignment | None:
    """
    Pick the best manager for this ticket (nearest office, then least loaded)
    and create an Assignment. Returns the assignment or None if no candidates.
    """
    candidates = await get_candidate_managers(ticket, db)
    if not candidates:
        log.warning("  [ROUTING] no candidate managers for ticket %s", ticket.id)
        return None

    best = candidates[0]
    manager = best.manager
    bu = best.business_unit
    distance_km = best.distance_km
    office_name = best.office_name or (bu.name if bu else None)

    # If we have multiple at similar distance, prefer lower stress (already sorted)
    dist_str = f", {distance_km:.1f} км от клиента" if distance_km != float("inf") and 0 <= distance_km < 1e6 else ""
    assignment = Assignment(
        ticket_id=ticket.id,
        manager_id=manager.id,
        business_unit_id=bu.id if bu else None,
        explanation=f"Назначено по территориальной близости: офис «{office_name or '—'}»{dist_str}",
        routing_details={
            "distance_km": round(distance_km, 2) if distance_km != float("inf") else None,
            "office_name": office_name,
            "ticket_city": ticket.city,
            "ticket_lat": ticket.latitude,
            "ticket_lon": ticket.longitude,
        },
    )
    db.add(assignment)
    ticket.assigned_manager_id = manager.id
    ticket.status = TicketStatusEnum.routed
    await db.flush()

    log.info(
        "  [ROUTING] ticket %s → %s (офис %s, %.1f км)",
        ticket.id, manager.full_name, office_name, distance_km,
    )
    return assignment
