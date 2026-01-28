"""Applications and stats API."""
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Application
from ..schemas import ApplicationStats, ApplicationResponse

router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/stats", response_model=ApplicationStats)
def get_stats(db: Session = Depends(get_db)):
    total = db.query(Application).count()
    rejections = db.query(Application).filter(Application.category == "REJECTION").count()
    interviews = db.query(Application).filter(Application.category == "INTERVIEW_REQUEST").count()
    assessments = db.query(Application).filter(Application.category == "ASSESSMENT").count()
    offers = db.query(Application).filter(Application.category == "OFFER").count()
    pending = total - (rejections + interviews + assessments + offers)
    return ApplicationStats(
        total_applications=total,
        rejections=rejections,
        interviews=interviews,
        assessments=assessments,
        pending=max(0, pending),
        offers=offers,
    )


@router.get("/applications", response_model=List[ApplicationResponse])
def get_applications(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(Application)
    if status and status != "ALL":
        query = query.filter(Application.category == status)
    applications = query.order_by(Application.received_date.desc().nulls_last()).limit(limit).all()
    return applications
