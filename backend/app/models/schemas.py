"""
Pydantic schemas for F.I.R.E. request/response validation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel, Field


# ── SSE Event ──

class SSEEvent(BaseModel):
    event_type: str
    ticket_id: uuid.UUID
    batch_id: Optional[uuid.UUID] = None
    stage: str
    status: str
    field: Optional[str] = None
    data: dict = Field(default_factory=dict)
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Ingest Responses ──

class IngestTicketsResponse(BaseModel):
    batch_id: uuid.UUID
    total_rows: int
    processed_rows: int
    failed_rows: int
    message: str
    errors: list = Field(default_factory=list)


class IngestManagersResponse(BaseModel):
    total_imported: int
    message: str
    errors: list = Field(default_factory=list)


class IngestBusinessUnitsResponse(BaseModel):
    total_imported: int
    message: str


# ── Ticket Schemas ──

class TicketResponse(BaseModel):
    id: uuid.UUID
    csv_row_index: Optional[int] = None
    guid: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    age: Optional[int] = None
    description: Optional[str] = None
    description_anonymized: Optional[str] = None
    attachments: list[str] = Field(default_factory=list)
    segment: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    street: Optional[str] = None
    house: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address_status: Optional[str] = None
    geo_explanation: Optional[str] = None
    ticket_type: Optional[str] = None
    status: str = "new"
    is_spam: bool = False
    spam_probability: float = 0.0
    text_length: Optional[int] = None
    text_length_times_age: Optional[float] = None
    id_count_of_user: int = 0
    assigned_manager_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Manager Schemas ──

class ManagerResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    position: str
    skill_factor: float
    skills: list[str] = Field(default_factory=list)
    business_unit_id: Optional[uuid.UUID] = None
    csv_load: int = 0
    stress_score: float = 0.0
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True


# ── Business Unit Schemas ──

class BusinessUnitResponse(BaseModel):
    id: uuid.UUID
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── AI Analysis Schemas ──

class AIAnalysisResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    detected_type: Optional[str] = None
    language_label: Optional[str] = None
    language_actual: Optional[str] = None
    language_is_mixed: bool = False
    language_note: Optional[str] = None
    summary: Optional[str] = None
    attachment_analysis: Optional[str] = None
    sentiment: Optional[str] = None
    sentiment_confidence: Optional[float] = None
    priority_base: Optional[float] = None
    priority_extra: Optional[float] = None
    priority_final: Optional[float] = None
    priority_breakdown: dict = Field(default_factory=dict)
    anomaly_flags: list = Field(default_factory=list)
    needs_data_change: bool = False
    needs_location_routing: bool = False
    processing_time_ms: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ── Assignment Schemas ──

class AssignmentResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    manager_id: uuid.UUID
    business_unit_id: Optional[uuid.UUID] = None
    explanation: Optional[str] = None
    routing_details: dict = Field(default_factory=dict)
    assigned_at: datetime

    class Config:
        from_attributes = True


# ── Processing State ──

class ProcessingStateResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    batch_id: Optional[uuid.UUID] = None
    stage: str
    status: str
    progress_pct: float = 0.0
    message: Optional[str] = None
    error_detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Batch Upload ──

class BatchUploadResponse(BaseModel):
    id: uuid.UUID
    filename: Optional[str] = None
    total_rows: int = 0
    processed_rows: int = 0
    failed_rows: int = 0
    status: str = "pending"
    error_log: list = Field(default_factory=list)
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── LLM / AI Result DTOs (internal, not API responses) ──

class LLMAnalysisResult(BaseModel):
    detected_type: str
    language_label: str
    language_actual: str
    language_is_mixed: bool = False
    language_note: Optional[str] = None
    summary: str
    attachment_analysis: Optional[str] = None
    needs_data_change: bool = False
    needs_location_routing: bool = False


class SentimentResult(BaseModel):
    sentiment: str
    confidence: float


class GeocodingResult(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider: Optional[str] = None
    address_status: str = "unknown"
    explanation: Optional[str] = None


# ── Ticket Lookup (row index) ──

class TicketLookupResponse(BaseModel):
    ticket: TicketResponse
    ai_analysis: Optional[AIAnalysisResponse] = None
    assignment: Optional[AssignmentResponse] = None
    manager: Optional[ManagerResponse] = None
    business_unit: Optional[BusinessUnitResponse] = None
