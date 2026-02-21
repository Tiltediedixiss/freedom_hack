"""
API routes for CSV data ingestion (T2).
  POST /api/ingest/tickets        — upload tickets CSV
  POST /api/ingest/managers       — upload managers CSV
  POST /api/ingest/business-units — upload business_units CSV
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.schemas import (
    IngestTicketsResponse, IngestManagersResponse, IngestBusinessUnitsResponse,
)
from app.services.csv_parser import (
    ingest_tickets_csv, ingest_managers_csv, ingest_business_units_csv,
)

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])
settings = get_settings()


def _validate_csv(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")


@router.post("/tickets", response_model=IngestTicketsResponse)
async def upload_tickets_csv(
    file: UploadFile = File(..., description="Tickets CSV file"),
    db: AsyncSession = Depends(get_db),
):
    """Upload tickets CSV for ingestion with feature engineering."""
    _validate_csv(file)
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB.")

    result = await ingest_tickets_csv(db, contents, file.filename)

    return IngestTicketsResponse(
        batch_id=result["batch_id"],
        total_rows=result["total_rows"],
        processed_rows=result["processed_rows"],
        failed_rows=result["failed_rows"],
        message=f"Ingested {result['processed_rows']}/{result['total_rows']} tickets "
                f"({result['failed_rows']} failed)",
        errors=result["errors"],
    )


@router.post("/managers", response_model=IngestManagersResponse)
async def upload_managers_csv(
    file: UploadFile = File(..., description="Managers CSV file"),
    db: AsyncSession = Depends(get_db),
):
    """Upload managers CSV. Links to business_units by office name."""
    _validate_csv(file)
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB.")

    result = await ingest_managers_csv(db, contents, file.filename)

    return IngestManagersResponse(
        total_imported=result["total_imported"],
        message=f"Imported {result['total_imported']} managers",
        errors=result["errors"],
    )


@router.post("/business-units", response_model=IngestBusinessUnitsResponse)
async def upload_business_units_csv(
    file: UploadFile = File(..., description="Business Units CSV file"),
    db: AsyncSession = Depends(get_db),
):
    """Upload business_units CSV (offices with addresses)."""
    _validate_csv(file)
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB.")

    result = await ingest_business_units_csv(db, contents, file.filename)

    return IngestBusinessUnitsResponse(
        total_imported=result["total_imported"],
        message=f"Imported {result['total_imported']} business units",
    )
