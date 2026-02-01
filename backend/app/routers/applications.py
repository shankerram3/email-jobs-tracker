"""Applications API: list with pagination, stats, schedule, respond."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Application
from ..langgraph_pipeline import EMAIL_CATEGORIES
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


@router.get("/stats", response_model=ApplicationStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    total = await db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == current_user.id)
    )
    total = int(total or 0)

    # Stage-based stats (category now holds the 14 LangGraph classes).
    rejections = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == current_user.id, Application.application_stage == "Rejected")
    )
    offers = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == current_user.id, Application.application_stage == "Offer")
    )
    screening_requests = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == current_user.id, Application.application_stage == "Screening")
    )
    rejections = int(rejections or 0)
    offers = int(offers or 0)
    screening_requests = int(screening_requests or 0)

    # Split interview vs assessment heuristically within interview_assessment.
    assessment_terms = [
        "%assessment%",
        "%codesignal%",
        "%hackerrank%",
        "%codility%",
        "%take-home%",
        "%take home%",
        "%technical test%",
        "%coding challenge%",
    ]
    assessment_like = or_(
        *[
            or_(
                Application.email_subject.ilike(t),
                Application.email_body.ilike(t),
            )
            for t in assessment_terms
        ]
    )
    assessments = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(
            Application.user_id == current_user.id,
            Application.category == "interview_assessment",
            assessment_like,
        )
    )
    interviews = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(
            Application.user_id == current_user.id,
            Application.application_stage == "Interview",
            ~assessment_like,
        )
    )
    assessments = int(assessments or 0)
    interviews = int(interviews or 0)

    pending = total - (rejections + interviews + screening_requests + assessments + offers)
    return ApplicationStats(
        total_applications=total,
        rejections=rejections,
        interviews=interviews,
        screening_requests=screening_requests,
        assessments=assessments,
        pending=max(0, pending),
        offers=offers,
    )


@router.get("/applications", response_model=PaginatedApplications)
async def get_applications(
    status: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    where_clause = (Application.user_id == current_user.id)
    if status and status != "ALL":
        # Backward compatible filters for the old UI + new stage/category filters.
        assessment_terms = [
            "%assessment%",
            "%codesignal%",
            "%hackerrank%",
            "%codility%",
            "%take-home%",
            "%take home%",
            "%technical test%",
            "%coding challenge%",
        ]
        assessment_like = or_(
            *[
                or_(
                    Application.email_subject.ilike(t),
                    Application.email_body.ilike(t),
                )
                for t in assessment_terms
            ]
        )

        if status == "INTERVIEW_OR_SCREENING":
            where_clause = where_clause & Application.application_stage.in_(["Interview", "Screening"])
        elif status == "ASSESSMENT":
            where_clause = where_clause & (Application.category == "interview_assessment") & assessment_like
        elif status in ("REJECTION", "REJECTED"):
            where_clause = where_clause & (Application.application_stage == "Rejected")
        elif status == "OFFER":
            where_clause = where_clause & (Application.application_stage == "Offer")
        elif status == "APPLIED":
            where_clause = where_clause & (Application.application_stage == "Applied")
        elif status == "SCREENING":
            where_clause = where_clause & (Application.application_stage == "Screening")
        elif status == "INTERVIEW":
            where_clause = where_clause & (Application.application_stage == "Interview")
        elif status in ("CONTACTED", "PIPELINE", "OTHER"):
            where_clause = where_clause & (Application.application_stage == status.title())
        elif status in EMAIL_CATEGORIES:
            # Category filter for 14 classes.
            where_clause = where_clause & (Application.category == status)
        else:
            # Fall back to treating it as stage name if it matches.
            where_clause = where_clause & (Application.application_stage == status)

    total = await db.scalar(select(func.count()).select_from(Application).where(where_clause))
    total = int(total or 0)
    result = await db.execute(
        select(Application)
        .where(where_clause)
        .order_by(Application.received_date.desc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    applications = list(result.scalars().all())
    return PaginatedApplications(items=applications, total=total, offset=offset, limit=limit)


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    result = await db.execute(
        select(Application).where(Application.user_id == current_user.id, Application.id == application_id)
    )
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.post("/applications/{application_id}/schedule")
async def schedule_application(
    application_id: int,
    body: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Calendar integration: schedule event (placeholder; integrate Google Calendar when configured)."""
    result = await db.execute(
        select(Application).where(Application.user_id == current_user.id, Application.id == application_id)
    )
    app = result.scalars().first()
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
async def respond_application(
    application_id: int,
    body: RespondRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Auto-response placeholder (e.g. send reply via Gmail when implemented)."""
    result = await db.execute(
        select(Application).where(Application.user_id == current_user.id, Application.id == application_id)
    )
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {
        "message": "Respond requested.",
        "application_id": application_id,
        "template": body.template,
    }
