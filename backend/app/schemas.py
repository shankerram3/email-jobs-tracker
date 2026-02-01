"""Pydantic schemas for API."""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


class ApplicationStats(BaseModel):
    total_applications: int
    rejections: int
    interviews: int
    screening_requests: int
    assessments: int
    pending: int
    offers: int


class ApplicationResponse(BaseModel):
    id: int
    company_name: str
    position: Optional[str] = None
    status: str
    category: str
    subcategory: Optional[str] = None
    job_title: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    location: Optional[str] = None
    confidence: Optional[float] = None
    # LangGraph fields (now used by the React UI)
    classification_reasoning: Optional[str] = None
    position_level: Optional[str] = None
    application_stage: Optional[str] = None
    requires_action: bool = False
    action_items: Optional[List[str]] = None
    resume_matched: Optional[str] = None
    processing_status: Optional[str] = None
    received_date: Optional[datetime] = None
    email_subject: str
    email_from: Optional[str] = None
    email_body: Optional[str] = None
    applied_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    interview_at: Optional[datetime] = None
    offer_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaginatedApplications(BaseModel):
    items: List[ApplicationResponse]
    total: int
    offset: int
    limit: int


# Analytics
class FunnelStage(BaseModel):
    stage: str
    count: int
    pct: Optional[float] = None


class FunnelResponse(BaseModel):
    funnel: List[FunnelStage]
    total: int


class ResponseRateItem(BaseModel):
    name: str
    applied: int
    responded: int
    rate: float


class ResponseRateResponse(BaseModel):
    group_by: str
    items: List[ResponseRateItem]


class TimeToEventResponse(BaseModel):
    event: str
    median_days: Optional[float] = None
    avg_days: Optional[float] = None
    sample_size: int


class PredictionItem(BaseModel):
    application_id: int
    company_name: str
    probability: float
    features: Optional[dict] = None


class PredictionResponse(BaseModel):
    items: List[PredictionItem]
    limit: int


# Actions
class ScheduleRequest(BaseModel):
    calendar_event_at: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None


class RespondRequest(BaseModel):
    message: Optional[str] = None
    template: Optional[str] = None


# =============================================================================
# LangGraph Classification Schemas
# =============================================================================

class EmailInput(BaseModel):
    """Input for processing a single email."""
    email_id: str
    subject: str
    body: str
    sender: str
    received_date: Optional[str] = None


class ClassificationResult(BaseModel):
    """Result from LangGraph classification pipeline."""
    email_id: str
    email_class: str
    confidence: float
    classification_reasoning: Optional[str] = None
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    position_level: Optional[str] = None
    application_stage: str
    requires_action: bool
    action_items: List[str] = []
    resume_matched: Optional[str] = None
    processing_status: str
    errors: List[str] = []


class ApplicationDetailResponse(BaseModel):
    """Extended application response with LangGraph fields."""
    id: int
    gmail_message_id: str
    company_name: str
    position: Optional[str] = None
    status: str
    category: str
    email_subject: str
    email_from: Optional[str] = None
    received_date: Optional[datetime] = None
    created_at: datetime

    # LangGraph classification fields
    confidence: Optional[float] = None
    classification_reasoning: Optional[str] = None
    position_level: Optional[str] = None
    application_stage: Optional[str] = None
    requires_action: bool = False
    action_items: Optional[List[str]] = None
    resume_matched: Optional[str] = None
    processing_status: Optional[str] = None

    class Config:
        from_attributes = True


class CategoryStats(BaseModel):
    """Statistics for a single category."""
    category: str
    count: int
    avg_confidence: Optional[float] = None
    requires_action_count: int = 0


class ClassificationAnalytics(BaseModel):
    """Overall classification analytics."""
    total_processed: int
    by_category: List[CategoryStats]
    by_stage: dict
    action_required_count: int
    avg_confidence: Optional[float] = None


# =============================================================================
# Reprocess pipeline schemas
# =============================================================================


class ReprocessStartRequest(BaseModel):
    """Start a DB reprocess job for existing applications."""

    only_needs_review: bool = True
    min_confidence: Optional[float] = None
    limit: int = 500
    batch_size: int = 25
    dry_run: bool = False


class ReprocessStartResponse(BaseModel):
    task_id: str
    status: str = "queued"


class ReprocessStatusResponse(BaseModel):
    status: str = "idle"
    message: str = ""
    processed: int = 0
    total: int = 0
    error: Optional[str] = None
    task_id: Optional[str] = None
    params: Optional[dict] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    celery_state: Optional[str] = None
