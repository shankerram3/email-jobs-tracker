"""Pydantic schemas for API."""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


class ApplicationStats(BaseModel):
    total_applications: int
    rejections: int
    interviews: int
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
    received_date: Optional[datetime] = None
    email_subject: str
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
