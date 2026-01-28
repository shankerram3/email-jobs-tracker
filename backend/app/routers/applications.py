"""Applications API: list with pagination, stats, schedule, respond."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from ..database import get_db
from ..models import Application
from ..schemas import (
    ApplicationStats,
    ApplicationResponse,
    PaginatedApplications,
    ScheduleRequest,
    RespondRequest,
)
from ..auth import get_current_user_required
from ..models import User

router = APIRouter(prefix="/api", tags=["applications"])


def _app_query(db, user: User):
    return db.query(Application).filter(Application.user_id == user.id)


@router.get("/stats", response_model=ApplicationStats)
def get_stats(
    db=Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    q = _app_query(db, current_user)
    total = q.count()
    rejections = q.filter(Application.category == "REJECTION").count()
    interviews = q.filter(Application.category == "INTERVIEW_REQUEST").count()
    assessments = q.filter(Application.category == "ASSESSMENT").count()
    offers = q.filter(Application.category == "OFFER").count()
    pending = total - (rejections + interviews + assessments + offers)
    return ApplicationStats(
        total_applications=total,
        rejections=rejections,
        interviews=interviews,
        assessments=assessments,
        pending=max(0, pending),
        offers=offers,
    )


@router.get("/applications", response_model=PaginatedApplications)
def get_applications(
    status: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    query = _app_query(db, current_user)
    if status and status != "ALL":
        query = query.filter(Application.category == status)
    total = query.count()
    applications = (
        query.order_by(Application.received_date.desc().nulls_last())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return PaginatedApplications(items=applications, total=total, offset=offset, limit=limit)


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    app = _app_query(db, current_user).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.post("/applications/{application_id}/schedule")
def schedule_application(
    application_id: int,
    body: ScheduleRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Calendar integration: schedule event (placeholder; integrate Google Calendar when configured)."""
    app = _app_query(db, current_user).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    # TODO: call Google Calendar API when credentials available
    return {
        "message": "Schedule requested.",
        "application_id": application_id,
        "calendar_event_at": body.calendar_event_at,
        "title": body.title or f"Interview - {app.company_name}",
    }


@router.post("/applications/{application_id}/respond")
def respond_application(
    application_id: int,
    body: RespondRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Auto-response placeholder (e.g. send reply via Gmail when implemented)."""
    app = _app_query(db, current_user).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {
        "message": "Respond requested.",
        "application_id": application_id,
        "template": body.template,
    }
