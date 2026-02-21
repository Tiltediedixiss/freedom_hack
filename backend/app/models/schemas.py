"""
Pydantic schemas for request/response validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── Manager Schemas ──


class ManagerBase(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    competencies: list[str] = Field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    max_tickets_per_day: int = 20
    is_active: bool = True


class ManagerCreate(ManagerBase):
    pass


class ManagerResponse(ManagerBase):
    id: uuid.UUID
    current_load: int = 0
    stress_score: float = 0.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Ticket Schemas ──


class TicketBase(BaseModel):
    external_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_age: Optional[int] = None
    subject: Optional[str] = None
    body: str
    language: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    attachment_urls: list[str] = Field(default_factory=list)


class TicketCreate(TicketBase):
    pass


class TicketResponse(BaseModel):
    id: uuid.UUID
    external_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_age: Optional[int] = None
    subject: Optional[str] = None
    body: str
    body_anonymized: Optional[str] = None
    language: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    attachment_urls: list[str] = Field(default_factory=list)
    ticket_type: Optional[str] = None
    status: str = "new"
    priority: Optional[str] = None
    priority_score: Optional[float] = None
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


class TicketSafeResponse(BaseModel):
    """PII-stripped ticket response for external consumption."""
    id: uuid.UUID
    external_id: Optional[str] = None
    body: Optional[str] = None  # This is body_anonymized
    language: Optional[str] = None
    ticket_type: Optional[str] = None
    status: str
    priority: Optional[str] = None
    priority_score: Optional[float] = None
    is_spam: bool = False
    spam_probability: float = 0.0
    text_length: Optional[int] = None
    text_length_times_age: Optional[float] = None
    id_count_of_user: int = 0
    assigned_manager_id: Optional[uuid.UUID] = None
    created_at: datetime
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    summary: Optional[str] = None

    class Config:
        from_attributes = True


# ── AI Analysis Schemas ──


class AIAnalysisResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    detected_type: Optional[str] = None
    detected_language: Optional[str] = None
    summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    key_phrases: list[str] = Field(default_factory=list)
    attachment_analysis: dict = Field(default_factory=dict)
    llm_model: Optional[str] = None
    llm_tokens_used: int = 0
    processing_time_ms: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ── Processing State Schemas ──


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


# ── Batch Upload Schemas ──


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


# ── SSE Event Schema ──


class SSEEvent(BaseModel):
    """Schema for Server-Sent Events pushed to frontend."""
    event_type: str  # e.g. "ingestion", "spam_check", "sentiment", etc.
    ticket_id: uuid.UUID
    batch_id: Optional[uuid.UUID] = None
    stage: str
    status: str
    data: dict = Field(default_factory=dict)
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Ingest Request Schemas ──


class IngestResponse(BaseModel):
    batch_id: uuid.UUID
    total_rows: int
    message: str


class IngestManagersResponse(BaseModel):
    total_imported: int
    message: str
