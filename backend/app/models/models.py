"""
SQLAlchemy ORM models for the F.I.R.E. system.
Maps to the tables created in docker/init.sql.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography

from app.core.database import Base


# ── Enums ──

import enum


class TicketStatusEnum(str, enum.Enum):
    new = "new"
    ingested = "ingested"
    pii_stripped = "pii_stripped"
    spam_checked = "spam_checked"
    analyzing = "analyzing"
    enriched = "enriched"
    routed = "routed"
    closed = "closed"


class TicketTypeEnum(str, enum.Enum):
    complaint = "complaint"
    request = "request"
    suggestion = "suggestion"
    question = "question"
    other = "other"


class PriorityLevelEnum(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ProcessingStageEnum(str, enum.Enum):
    ingestion = "ingestion"
    pii_anonymization = "pii_anonymization"
    spam_filter = "spam_filter"
    llm_analysis = "llm_analysis"
    sentiment_analysis = "sentiment_analysis"
    geocoding = "geocoding"
    feature_engineering = "feature_engineering"
    priority_calculation = "priority_calculation"
    routing = "routing"


class StageStatusEnum(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


# ── Models ──


class Manager(Base):
    __tablename__ = "managers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True)
    phone = Column(String(50))
    competencies = Column(ARRAY(Text), default=[])
    latitude = Column(Double)
    longitude = Column(Double)
    geo_point = Column(Geography(geometry_type="POINT", srid=4326))
    max_tickets_per_day = Column(Integer, default=20)
    current_load = Column(Integer, default=0)
    stress_score = Column(Double, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assigned_tickets = relationship("Ticket", back_populates="assigned_manager")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = Column(String(255))
    user_name = Column(String(255))
    user_email = Column(String(255))
    user_age = Column(Integer)
    subject = Column(String(500))
    body = Column(Text, nullable=False)
    body_anonymized = Column(Text)
    language = Column(String(10))
    latitude = Column(Double)
    longitude = Column(Double)
    geo_point = Column(Geography(geometry_type="POINT", srid=4326))
    address = Column(Text)
    attachment_urls = Column(ARRAY(Text), default=[])
    ticket_type = Column(
        Enum(TicketTypeEnum, name="ticket_type", create_type=False),
        default=TicketTypeEnum.other,
    )
    status = Column(
        Enum(TicketStatusEnum, name="ticket_status", create_type=False),
        default=TicketStatusEnum.new,
    )
    priority = Column(Enum(PriorityLevelEnum, name="priority_level", create_type=False))
    priority_score = Column(Double)
    is_spam = Column(Boolean, default=False)
    spam_probability = Column(Double, default=0.0)
    text_length = Column(Integer)
    text_length_times_age = Column(Double)
    id_count_of_user = Column(Integer, default=0)

    assigned_manager_id = Column(UUID(as_uuid=True), ForeignKey("managers.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assigned_manager = relationship("Manager", back_populates="assigned_tickets")
    ai_analysis = relationship("AIAnalysis", back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    pii_mappings = relationship("PIIMapping", back_populates="ticket", cascade="all, delete-orphan")
    processing_states = relationship("ProcessingState", back_populates="ticket", cascade="all, delete-orphan")


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    detected_type = Column(Enum(TicketTypeEnum, name="ticket_type", create_type=False))
    detected_language = Column(String(10))
    summary = Column(Text)
    summary_anonymized = Column(Text)
    sentiment_score = Column(Double)
    sentiment_label = Column(String(50))
    key_phrases = Column(ARRAY(Text), default=[])
    attachment_analysis = Column(JSONB, default={})
    llm_model = Column(String(100))
    llm_tokens_used = Column(Integer, default=0)
    processing_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="ai_analysis")


class PIIMapping(Base):
    __tablename__ = "pii_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(100), nullable=False)
    original_value = Column(Text, nullable=False)
    pii_type = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="pii_mappings")


class ProcessingState(Base):
    __tablename__ = "processing_state"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    batch_id = Column(UUID(as_uuid=True))
    stage = Column(
        Enum(ProcessingStageEnum, name="processing_stage", create_type=False),
        nullable=False,
    )
    status = Column(
        Enum(StageStatusEnum, name="stage_status", create_type=False),
        default=StageStatusEnum.pending,
    )
    progress_pct = Column(Double, default=0.0)
    message = Column(Text)
    error_detail = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    ticket = relationship("Ticket", back_populates="processing_states")


class GeocodingCache(Base):
    __tablename__ = "geocoding_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address_query = Column(Text, nullable=False, unique=True)
    latitude = Column(Double)
    longitude = Column(Double)
    provider = Column(String(50))
    raw_response = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class BatchUpload(Base):
    __tablename__ = "batch_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(500))
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    status = Column(String(50), default="pending")
    error_log = Column(JSONB, default=[])
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
