"""SQLAlchemy models."""
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
    Boolean,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import JSON

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)  # null for Google-only users
    google_id = Column(String, nullable=True, index=True)  # Google OAuth sub
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    gmail_message_id = Column(String, index=True)  # unique per user (see composite index)
    company_name = Column(String, index=True)
    position = Column(String, nullable=True)
    status = Column(String, default="APPLIED")  # APPLIED, REJECTED, INTERVIEWING, OFFER
    category = Column(String, index=True)  # REJECTION, INTERVIEW_REQUEST, etc.
    subcategory = Column(String, nullable=True, index=True)
    job_title = Column(String, nullable=True, index=True)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    location = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    email_subject = Column(String)
    email_from = Column(String)
    email_body = Column(Text, nullable=True)
    received_date = Column(DateTime, nullable=True)
    # Status transition timestamps
    applied_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    interview_at = Column(DateTime, nullable=True)
    offer_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    linkedin_url = Column(String, nullable=True)

    # LangGraph classification fields
    classification_reasoning = Column(Text, nullable=True)  # Why this category
    position_level = Column(String, nullable=True)  # Junior/Mid/Senior/Staff/Principal

    # Application stage tracking
    application_stage = Column(String, default="Other")  # Applied, Screening, Interview, Offer, Rejected
    requires_action = Column(Boolean, default=False)
    action_items = Column(JSON, nullable=True)  # List of action strings

    # Resume matching (placeholder for future Google Drive integration)
    resume_matched = Column(String, nullable=True)
    resume_file_id = Column(String, nullable=True)
    resume_version = Column(String, nullable=True)

    # Processing metadata
    processing_status = Column(String, default="pending")  # pending, completed, failed
    processed_by = Column(String, nullable=True)  # Model version that processed this

    # Review flagging
    needs_review = Column(Boolean, default=False, nullable=True)  # Flag for low-confidence classifications


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    gmail_message_id = Column(String, index=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
    classification = Column(String, nullable=True)
    error = Column(Text, nullable=True)


class SyncMetadata(Base):
    """Key-value store for backward compatibility (e.g. last_synced_at)."""
    __tablename__ = "sync_metadata"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncState(Base):
    """Gmail sync state for history-based incremental sync (per user)."""
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    last_history_id = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_full_sync_at = Column(DateTime, nullable=True)
    status = Column(String, default="idle")  # idle, syncing, error
    error = Column(Text, nullable=True)
    processed = Column(Integer, default=0, nullable=True)
    total = Column(Integer, default=0, nullable=True)
    message = Column(String(255), nullable=True)
    created = Column(Integer, default=0, nullable=True)
    skipped = Column(Integer, default=0, nullable=True)
    errors = Column(Integer, default=0, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OAuthState(Base):
    """OAuth CSRF state for Gmail and Google Sign-in (shared store)."""
    __tablename__ = "oauth_state"

    state_token = Column(String(64), primary_key=True)
    kind = Column(String(32), nullable=False, index=True)  # gmail, google_login
    redirect_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False)


class Company(Base):
    """Canonical company names and optional aliases."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(String, unique=True, index=True, nullable=False)
    aliases = Column(JSON, nullable=True)  # list of strings
    industry = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClassificationCache(Base):
    """Cache for structured LLM classification keyed by content hash."""
    __tablename__ = "classification_cache"

    id = Column(Integer, primary_key=True, index=True)
    content_hash = Column(String(64), unique=True, index=True, nullable=False)
    category = Column(String, nullable=False)
    subcategory = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    location = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    raw_json = Column(Text, nullable=True)  # full structured payload as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class Resume(Base):
    """Resume metadata for matching applications to resume versions."""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    drive_file_id = Column(String, nullable=True, index=True)
    version = Column(String, nullable=True, index=True)
    company = Column(String, nullable=True, index=True)
    job_title = Column(String, nullable=True, index=True)
    specialization = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Indexes for analytics and filtering
Index("ix_applications_category_received_date", Application.category, Application.received_date)
Index("ix_applications_status_received_date", Application.status, Application.received_date)
Index("ix_applications_received_date", Application.received_date)
Index("ix_applications_user_gmail", Application.user_id, Application.gmail_message_id, unique=True)
