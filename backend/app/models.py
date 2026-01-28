"""SQLAlchemy models."""
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


# Indexes for analytics and filtering
Index("ix_applications_category_received_date", Application.category, Application.received_date)
Index("ix_applications_status_received_date", Application.status, Application.received_date)
Index("ix_applications_received_date", Application.received_date)
Index("ix_applications_user_gmail", Application.user_id, Application.gmail_message_id, unique=True)
