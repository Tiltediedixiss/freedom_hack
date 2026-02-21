"""
Dashboard API — aggregated stats and distributions.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import AIAnalysis, Assignment, Manager, Ticket

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Aggregated dashboard statistics."""
    total = await db.execute(select(func.count(Ticket.id)))
    spam = await db.execute(select(func.count(Ticket.id)).where(Ticket.is_spam == True))
    mgrs = await db.execute(select(func.count(Manager.id)))
    assigned = await db.execute(select(func.count(Assignment.id)))

    # Status distribution
    status_q = await db.execute(
        select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
    )

    return {
        "total_tickets": total.scalar() or 0,
        "spam_tickets": spam.scalar() or 0,
        "total_managers": mgrs.scalar() or 0,
        "total_assignments": assigned.scalar() or 0,
        "by_status": {row[0]: row[1] for row in status_q},
    }


@router.get("/types")
async def type_distribution(db: AsyncSession = Depends(get_db)):
    """Ticket type distribution from AI analysis."""
    result = await db.execute(
        select(AIAnalysis.detected_type, func.count(AIAnalysis.id))
        .group_by(AIAnalysis.detected_type)
    )
    return {row[0]: row[1] for row in result if row[0]}


@router.get("/sentiment")
async def sentiment_distribution(db: AsyncSession = Depends(get_db)):
    """Sentiment distribution."""
    result = await db.execute(
        select(AIAnalysis.sentiment, func.count(AIAnalysis.id))
        .group_by(AIAnalysis.sentiment)
    )
    return {row[0]: row[1] for row in result if row[0]}


@router.get("/managers")
async def manager_load(db: AsyncSession = Depends(get_db)):
    """Manager load overview."""
    result = await db.execute(
        select(Manager).order_by(Manager.stress_score.desc())
    )
    managers = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "full_name": m.full_name,
            "position": m.position.value if m.position else None,
            "skills": m.skills,
            "csv_load": m.csv_load,
            "stress_score": m.stress_score,
        }
        for m in managers
    ]
