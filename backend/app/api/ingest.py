"""
API routes for CSV data ingestion (T2).
  POST /api/ingest/tickets   — upload tickets CSV
  POST /api/ingest/managers  — upload managers CSV
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.schemas import IngestResponse, IngestManagersResponse
from app.services.csv_parser import ingest_tickets_csv, ingest_managers_csv

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])
settings = get_settings()


@router.post("/tickets", response_model=IngestResponse)
async def upload_tickets_csv(
    file: UploadFile = File(..., description="Tickets CSV file"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a CSV containing support tickets.
    Parses, validates, ingests into DB, and computes Stage 1 features.
    Streams per-row progress via SSE.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    # Check file size
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB allowed.",
        )

    result = await ingest_tickets_csv(db, contents, file.filename)

    return IngestResponse(
        batch_id=result["batch_id"],
        total_rows=result["total_rows"],
        message=f"Ingested {result['processed_rows']}/{result['total_rows']} tickets "
                f"({result['failed_rows']} failed)",
    )


@router.post("/managers", response_model=IngestManagersResponse)
async def upload_managers_csv(
    file: UploadFile = File(..., description="Managers CSV file"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a CSV containing manager profiles.
    Parses and upserts managers into the database.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB allowed.",
        )

    result = await ingest_managers_csv(db, contents, file.filename)

    return IngestManagersResponse(
        total_imported=result["total_imported"],
        message=f"Imported {result['total_imported']} managers from '{file.filename}'",
    )
