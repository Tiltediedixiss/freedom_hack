"""
SQLAlchemy ORM models for the F.I.R.E. system.
Aligned with spec: Russian enums, business_units, assignments, audit_log.
"""

import uuid
import enum
from datetime import datetime, date

from sqlalchemy import (
    Boolean, Column, DateTime, Date, Double, Enum,
    ForeignKey, Integer, LargeBinary, String, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography

from app.core.database import Base


# ── Enums ──

class TicketTypeEnum(str, enum.Enum):
    # Names MUST match PostgreSQL enum values (SQLAlchemy sends names, not values)
    жалоба = "жалоба"
    смена_данных = "смена_данных"
    консультация = "консультация"
    претензия = "претензия"
    неработоспособность = "неработоспособность"
    мошенничество = "мошенничество"
    спам = "спам"


class SentimentEnum(str, enum.Enum):
    позитивный = "позитивный"
    нейтральный = "нейтральный"
    негативный = "негативный"


class SegmentEnum(str, enum.Enum):
    VIP = "VIP"
    Priority = "Priority"
    Mass = "Mass"


class ManagerPositionEnum(str, enum.Enum):
    специалист = "специалист"
    ведущий_специалист = "ведущий_специалист"
    главный_специалист = "главный_специалист"


class TicketStatusEnum(str, enum.Enum):
    new = "new"
    ingested = "ingested"
    pii_stripped = "pii_stripped"
    spam_checked = "spam_checked"
    analyzing = "analyzing"
    enriched = "enriched"
    routed = "routed"
    closed = "closed"


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


class AddressStatusEnum(str, enum.Enum):
    resolved = "resolved"
    unknown = "unknown"
    foreign = "foreign"
    partial = "partial"


# ── Lookup constants ──

POSITION_SKILL_FACTOR = {
    ManagerPositionEnum.специалист: 1.0,
    ManagerPositionEnum.ведущий_специалист: 1.3,
    ManagerPositionEnum.главный_специалист: 1.5,
}

COMPLEXITY_WEIGHTS = {
    TicketTypeEnum.мошенничество: 5,
    TicketTypeEnum.претензия: 4,
    TicketTypeEnum.жалоба: 3,
    TicketTypeEnum.неработоспособность: 3,
    TicketTypeEnum.смена_данных: 2,
    TicketTypeEnum.консультация: 1,
    TicketTypeEnum.спам: 0,
}

# CSV position text → enum mapping
POSITION_MAP = {
    "специалист": ManagerPositionEnum.специалист,
    "ведущий специалист": ManagerPositionEnum.ведущий_специалист,
    "главный специалист": ManagerPositionEnum.главный_специалист,
}

# CSV segment text → enum mapping
SEGMENT_MAP = {
    "vip": SegmentEnum.VIP,
    "priority": SegmentEnum.Priority,
    "mass": SegmentEnum.Mass,
    "mass market": SegmentEnum.Mass,
}


# ── Models ──

class BusinessUnit(Base):
    __tablename__ = "business_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    address = Column(Text)
    latitude = Column(Double)
    longitude = Column(Double)
    geo_point = Column(Geography(geometry_type="POINT", srid=4326))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    managers = relationship("Manager", back_populates="business_unit")


class Manager(Base):
    __tablename__ = "managers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String(255), nullable=False)
    position = Column(
        Enum(ManagerPositionEnum, name="manager_position", create_type=False),
        nullable=False, default=ManagerPositionEnum.специалист,
    )
    skill_factor = Column(Double, default=1.0)
    skills = Column(ARRAY(Text), default=[])
    business_unit_id = Column(UUID(as_uuid=True), ForeignKey("business_units.id"))
    csv_load = Column(Integer, default=0)
    stress_score = Column(Double, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    business_unit = relationship("BusinessUnit", back_populates="managers")
    assignments = relationship("Assignment", back_populates="manager")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    csv_row_index = Column(Integer)
    guid = Column(String(255))
    gender = Column(String(20))
    birth_date = Column(Date)
    age = Column(Integer)
    description = Column(Text)
    description_anonymized = Column(Text)
    attachments = Column(ARRAY(Text), default=[])
    segment = Column(Enum(SegmentEnum, name="segment_type", create_type=False))
    country = Column(String(255))
    region = Column(String(255))
    city = Column(String(255))
    street = Column(String(255))
    house = Column(String(100))
    latitude = Column(Double)
    longitude = Column(Double)
    geo_point = Column(Geography(geometry_type="POINT", srid=4326))
    address_status = Column(
        Enum(AddressStatusEnum, name="address_status", create_type=False),
        default=AddressStatusEnum.unknown,
    )
    ticket_type = Column(Enum(TicketTypeEnum, name="ticket_type", create_type=False))
    status = Column(
        Enum(TicketStatusEnum, name="ticket_status", create_type=False),

        default=TicketStatusEnum.new,
    )
    is_spam = Column(Boolean, default=False)
    spam_probability = Column(Double, default=0.0)
    text_length = Column(Integer)
    text_length_times_age = Column(Double)
    id_count_of_user = Column(Integer, default=0)
    assigned_manager_id = Column(UUID(as_uuid=True), ForeignKey("managers.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    ai_analysis = relationship("AIAnalysis", back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    pii_mappings = relationship("PIIMapping", back_populates="ticket", cascade="all, delete-orphan")
    processing_states = relationship("ProcessingState", back_populates="ticket", cascade="all, delete-orphan")
    assignment = relationship("Assignment", back_populates="ticket", uselist=False, cascade="all, delete-orphan")


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    detected_type = Column(Enum(TicketTypeEnum, name="ticket_type", create_type=False))
    language_label = Column(String(10))
    language_actual = Column(String(50))
    language_is_mixed = Column(Boolean, default=False)
    language_note = Column(Text)
    summary = Column(Text)
    summary_anonymized = Column(Text)
    attachment_analysis = Column(Text)
    sentiment = Column(Enum(SentimentEnum, name="sentiment_type", create_type=False))
    sentiment_confidence = Column(Double)
    priority_base = Column(Double)
    priority_extra = Column(Double)
    priority_final = Column(Double)
    priority_breakdown = Column(JSONB, default={})
    anomaly_flags = Column(JSONB, default=[])
    needs_data_change = Column(Boolean, default=False)
    needs_location_routing = Column(Boolean, default=False)
    llm_model = Column(String(100))
    llm_tokens_used = Column(Integer, default=0)
    processing_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="ai_analysis")


class PIIMapping(Base):
    __tablename__ = "pii_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(100), nullable=False)
    original_value = Column(LargeBinary, nullable=False)  # pgcrypto encrypted
    pii_type = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="pii_mappings")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("managers.id"), nullable=False)
    business_unit_id = Column(UUID(as_uuid=True), ForeignKey("business_units.id"))
    explanation = Column(Text)
    routing_details = Column(JSONB, default={})
    assigned_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="assignment")
    manager = relationship("Manager", back_populates="assignments")


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


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255))
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"))
    action = Column(String(100), nullable=False)
    details = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
