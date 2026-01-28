"""SQLAlchemy models."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    gmail_message_id = Column(String, unique=True, index=True)
    company_name = Column(String, index=True)
    position = Column(String, nullable=True)
    status = Column(String, default="APPLIED")  # APPLIED, REJECTED, INTERVIEWING, OFFER
    category = Column(String, index=True)  # REJECTION, INTERVIEW_REQUEST, etc.
    email_subject = Column(String)
    email_from = Column(String)
    email_body = Column(Text, nullable=True)
    received_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    gmail_message_id = Column(String, index=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
    classification = Column(String, nullable=True)
    error = Column(Text, nullable=True)


class SyncMetadata(Base):
    """Key-value store for sync state (e.g. last_synced_at)."""
    __tablename__ = "sync_metadata"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
