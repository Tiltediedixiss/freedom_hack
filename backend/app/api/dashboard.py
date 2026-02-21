"""
API routes for dashboard data (stub — will be expanded in T11-T12).
  GET /api/dashboard/stats — aggregated ticket statistics
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Manager, Ticket

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregated statistics for the dashboard."""

    # Total tickets
    total_result = await db.execute(select(func.count(Ticket.id)))
    total_tickets = total_result.scalar() or 0

    # Spam tickets
    spam_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.is_spam == True)
    )
    spam_tickets = spam_result.scalar() or 0

    # By status
    status_result = await db.execute(
        select(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
    )
    by_status = {row[0]: row[1] for row in status_result}

    # Total managers
    mgr_result = await db.execute(select(func.count(Manager.id)))
    total_managers = mgr_result.scalar() or 0

    return {
        "total_tickets": total_tickets,
        "spam_tickets": spam_tickets,
        "non_spam_tickets": total_tickets - spam_tickets,
        "by_status": by_status,
        "total_managers": total_managers,
    }
