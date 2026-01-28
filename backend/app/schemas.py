"""Pydantic schemas for API."""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional


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
    received_date: Optional[datetime] = None
    email_subject: str

    class Config:
        from_attributes = True
