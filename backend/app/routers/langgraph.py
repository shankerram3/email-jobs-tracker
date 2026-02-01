"""LangGraph email classification API endpoints."""
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from ..database import get_sync_db
from ..models import Application
from ..langgraph_pipeline import (
    process_email,
    get_all_categories,
    EMAIL_CATEGORIES,
)
from ..config import settings
from ..schemas import (
    EmailInput,
    ClassificationResult,
    ApplicationDetailResponse,
    CategoryStats,
    ClassificationAnalytics,
)

router = APIRouter(prefix="/api/langgraph", tags=["LangGraph Classification"])


@router.post("/process", response_model=ClassificationResult)
def process_single_email(
    email: EmailInput,
    persist: bool = False,
    db: Session = Depends(get_sync_db),
):
    """
    Process a single email through the LangGraph pipeline.
    Returns classification, entities, and action items.
    """
    try:
        result = process_email(
            email_id=email.email_id,
            subject=email.subject,
            body=email.body,
            sender=email.sender,
            received_date=email.received_date or "",
        )

        if persist:
            # Best-effort upsert: update existing application if found, else create a new one.
            app = (
                db.query(Application)
                .filter(Application.gmail_message_id == email.email_id)
                .order_by(Application.id.desc())
                .first()
            )
            stage = result.get("application_stage", "Other")
            status = "APPLIED"
            if stage == "Rejected":
                status = "REJECTED"
            elif stage in ("Interview", "Screening"):
                status = "INTERVIEWING"
            elif stage == "Offer":
                status = "OFFER"

            if app:
                app.category = result.get("email_class", app.category)
                app.company_name = result.get("company_name") or app.company_name
                app.position = result.get("job_title") or app.position
                app.job_title = result.get("job_title") or app.job_title
                app.confidence = result.get("confidence")
                app.classification_reasoning = result.get("classification_reasoning")
                app.position_level = result.get("position_level")
                app.application_stage = stage
                app.requires_action = result.get("requires_action", False)
                app.action_items = result.get("action_items", [])
                app.processing_status = result.get("processing_status", "completed")
                app.status = status
            else:
                model_name = getattr(settings, "openai_model", None) or "gpt-4o-mini"
                app = Application(
                    gmail_message_id=email.email_id,
                    user_id=None,
                    company_name=(result.get("company_name") or "Unknown")[:255],
                    position=(result.get("job_title") or None),
                    job_title=(result.get("job_title") or None),
                    status=status,
                    category=result.get("email_class", "promotional_marketing"),
                    confidence=result.get("confidence"),
                    classification_reasoning=result.get("classification_reasoning"),
                    position_level=result.get("position_level"),
                    application_stage=stage,
                    requires_action=result.get("requires_action", False),
                    action_items=result.get("action_items", []),
                    resume_matched=result.get("resume_matched"),
                    processing_status=result.get("processing_status", "completed"),
                    processed_by=f"langgraph-openai:{model_name}",
                    email_subject=(email.subject or "")[:500],
                    email_from=(email.sender or "")[:255],
                    email_body=(email.body or "")[:10000],
                )
                db.add(app)
            db.commit()

        return ClassificationResult(
            email_id=result.get("email_id", email.email_id),
            email_class=result.get("email_class", "promotional_marketing"),
            confidence=result.get("confidence", 0.0),
            classification_reasoning=result.get("classification_reasoning"),
            company_name=result.get("company_name"),
            job_title=result.get("job_title"),
            position_level=result.get("position_level"),
            application_stage=result.get("application_stage", "Other"),
            requires_action=result.get("requires_action", False),
            action_items=result.get("action_items", []),
            resume_matched=result.get("resume_matched"),
            processing_status=result.get("processing_status", "completed"),
            errors=result.get("errors", []),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_process")
async def batch_process_emails(
    emails: List[EmailInput],
    persist: bool = False,
    db: Session = Depends(get_sync_db),
):
    """
    Process multiple emails in parallel.
    """
    async def _one(e: EmailInput):
        # process_email is sync; run in a worker thread to allow concurrency.
        return await asyncio.to_thread(
            process_email,
            email_id=e.email_id,
            subject=e.subject,
            body=e.body,
            sender=e.sender,
            received_date=e.received_date or "",
        )

    results = await asyncio.gather(*[_one(e) for e in emails])

    if persist:
        for e, r in zip(emails, results):
            app = (
                db.query(Application)
                .filter(Application.gmail_message_id == e.email_id)
                .order_by(Application.id.desc())
                .first()
            )
            stage = r.get("application_stage", "Other")
            status = "APPLIED"
            if stage == "Rejected":
                status = "REJECTED"
            elif stage in ("Interview", "Screening"):
                status = "INTERVIEWING"
            elif stage == "Offer":
                status = "OFFER"
            if app:
                app.category = r.get("email_class", app.category)
                app.company_name = r.get("company_name") or app.company_name
                app.position = r.get("job_title") or app.position
                app.job_title = r.get("job_title") or app.job_title
                app.confidence = r.get("confidence")
                app.classification_reasoning = r.get("classification_reasoning")
                app.position_level = r.get("position_level")
                app.application_stage = stage
                app.requires_action = r.get("requires_action", False)
                app.action_items = r.get("action_items", [])
                app.processing_status = r.get("processing_status", "completed")
                app.status = status
            else:
                model_name = getattr(settings, "openai_model", None) or "gpt-4o-mini"
                db.add(
                    Application(
                        gmail_message_id=e.email_id,
                        user_id=None,
                        company_name=(r.get("company_name") or "Unknown")[:255],
                        position=(r.get("job_title") or None),
                        job_title=(r.get("job_title") or None),
                        status=status,
                        category=r.get("email_class", "promotional_marketing"),
                        confidence=r.get("confidence"),
                        classification_reasoning=r.get("classification_reasoning"),
                        position_level=r.get("position_level"),
                        application_stage=stage,
                        requires_action=r.get("requires_action", False),
                        action_items=r.get("action_items", []),
                        resume_matched=r.get("resume_matched"),
                        processing_status=r.get("processing_status", "completed"),
                        processed_by=f"langgraph-openai:{model_name}",
                        email_subject=(e.subject or "")[:500],
                        email_from=(e.sender or "")[:255],
                        email_body=(e.body or "")[:10000],
                    )
                )
        db.commit()

    return {"processed": len(results), "results": results}


@router.post("/reprocess/{application_id}", response_model=ApplicationDetailResponse)
def reprocess_application_endpoint(
    application_id: int,
    db: Session = Depends(get_sync_db),
):
    """
    Re-run LangGraph classification on an existing application.
    Useful after model updates or for manual review fixes.
    """
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    try:
        result = process_email(
            email_id=app.gmail_message_id,
            subject=app.email_subject or "",
            body=app.email_body or "",
            sender=app.email_from or "",
            received_date=app.received_date.isoformat() if app.received_date else "",
        )

        # Update application with new results
        app.category = result.get("email_class", app.category)
        app.company_name = result.get("company_name") or app.company_name
        app.position = result.get("job_title") or app.position
        app.confidence = result.get("confidence")
        app.classification_reasoning = result.get("classification_reasoning")
        app.position_level = result.get("position_level")
        app.application_stage = result.get("application_stage", "Other")
        app.requires_action = result.get("requires_action", False)
        app.action_items = result.get("action_items", [])
        app.processing_status = "completed"
        app.processed_by = "langgraph-gpt4o-mini-v1-reprocess"

        db.commit()
        db.refresh(app)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ApplicationDetailResponse(
        id=app.id,
        gmail_message_id=app.gmail_message_id,
        company_name=app.company_name,
        position=app.position,
        status=app.status,
        category=app.category,
        email_subject=app.email_subject,
        email_from=app.email_from,
        received_date=app.received_date,
        created_at=app.created_at,
        confidence=app.confidence,
        classification_reasoning=app.classification_reasoning,
        position_level=app.position_level,
        application_stage=app.application_stage,
        requires_action=app.requires_action,
        action_items=app.action_items,
        resume_matched=app.resume_matched,
        processing_status=app.processing_status,
    )


@router.get("/categories")
def list_categories():
    """
    List all 14 email classification categories with descriptions.
    """
    return {
        "categories": [
            {"name": name, "description": desc}
            for name, desc in EMAIL_CATEGORIES.items()
        ],
        "total": len(EMAIL_CATEGORIES),
    }


@router.get("/analytics", response_model=ClassificationAnalytics)
def get_classification_analytics(db: Session = Depends(get_sync_db)):
    """
    Get classification analytics across all processed applications.
    """
    # Total processed
    total = db.query(Application).count()

    # By category
    category_stats = (
        db.query(
            Application.category,
            func.count(Application.id).label("count"),
            func.avg(Application.confidence).label("avg_confidence"),
            func.sum(
                case((Application.requires_action == True, 1), else_=0)
            ).label("action_count"),
        )
        .group_by(Application.category)
        .all()
    )

    by_category = [
        CategoryStats(
            category=row.category or "unknown",
            count=row.count,
            avg_confidence=round(row.avg_confidence, 3) if row.avg_confidence else None,
            requires_action_count=int(row.action_count or 0),
        )
        for row in category_stats
    ]

    # By stage
    stage_stats = (
        db.query(
            Application.application_stage,
            func.count(Application.id).label("count"),
        )
        .group_by(Application.application_stage)
        .all()
    )
    by_stage = {row.application_stage or "Other": row.count for row in stage_stats}

    # Action required count
    action_count = (
        db.query(Application).filter(Application.requires_action == True).count()
    )

    # Overall average confidence
    avg_conf = db.query(func.avg(Application.confidence)).scalar()

    return ClassificationAnalytics(
        total_processed=total,
        by_category=by_category,
        by_stage=by_stage,
        action_required_count=action_count,
        avg_confidence=round(avg_conf, 3) if avg_conf else None,
    )


@router.get("/action-required", response_model=List[ApplicationDetailResponse])
def get_action_required(
    limit: int = 20,
    db: Session = Depends(get_sync_db),
):
    """
    Get applications that require user action (interviews, follow-ups, etc.)
    """
    apps = (
        db.query(Application)
        .filter(Application.requires_action == True)
        .order_by(Application.received_date.desc())
        .limit(limit)
        .all()
    )

    return [
        ApplicationDetailResponse(
            id=app.id,
            gmail_message_id=app.gmail_message_id,
            company_name=app.company_name,
            position=app.position,
            status=app.status,
            category=app.category,
            email_subject=app.email_subject,
            email_from=app.email_from,
            received_date=app.received_date,
            created_at=app.created_at,
            confidence=app.confidence,
            classification_reasoning=app.classification_reasoning,
            position_level=app.position_level,
            application_stage=app.application_stage,
            requires_action=app.requires_action,
            action_items=app.action_items,
            resume_matched=app.resume_matched,
            processing_status=app.processing_status,
        )
        for app in apps
    ]


@router.get("/low-confidence", response_model=List[ApplicationDetailResponse])
def get_low_confidence(
    threshold: float = 0.7,
    limit: int = 20,
    db: Session = Depends(get_sync_db),
):
    """
    Get applications with low classification confidence for manual review.
    """
    apps = (
        db.query(Application)
        .filter(Application.confidence < threshold)
        .filter(Application.confidence.isnot(None))
        .order_by(Application.confidence.asc())
        .limit(limit)
        .all()
    )

    return [
        ApplicationDetailResponse(
            id=app.id,
            gmail_message_id=app.gmail_message_id,
            company_name=app.company_name,
            position=app.position,
            status=app.status,
            category=app.category,
            email_subject=app.email_subject,
            email_from=app.email_from,
            received_date=app.received_date,
            created_at=app.created_at,
            confidence=app.confidence,
            classification_reasoning=app.classification_reasoning,
            position_level=app.position_level,
            application_stage=app.application_stage,
            requires_action=app.requires_action,
            action_items=app.action_items,
            resume_matched=app.resume_matched,
            processing_status=app.processing_status,
        )
        for app in apps
    ]


@router.get("/by-stage/{stage}", response_model=List[ApplicationDetailResponse])
def get_by_stage(
    stage: str,
    limit: int = 50,
    db: Session = Depends(get_sync_db),
):
    """
    Get applications by application stage (Applied, Interview, Rejected, etc.)
    """
    apps = (
        db.query(Application)
        .filter(Application.application_stage == stage)
        .order_by(Application.received_date.desc())
        .limit(limit)
        .all()
    )

    return [
        ApplicationDetailResponse(
            id=app.id,
            gmail_message_id=app.gmail_message_id,
            company_name=app.company_name,
            position=app.position,
            status=app.status,
            category=app.category,
            email_subject=app.email_subject,
            email_from=app.email_from,
            received_date=app.received_date,
            created_at=app.created_at,
            confidence=app.confidence,
            classification_reasoning=app.classification_reasoning,
            position_level=app.position_level,
            application_stage=app.application_stage,
            requires_action=app.requires_action,
            action_items=app.action_items,
            resume_matched=app.resume_matched,
            processing_status=app.processing_status,
        )
        for app in apps
    ]
