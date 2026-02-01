"""Reprocess pipeline API: reclassify existing DB applications."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from celery.result import AsyncResult

from ..auth import get_current_user_required
from ..database import get_sync_db
from ..models import User
from ..reprocess_state_db import get_reprocess_state, set_reprocess_state_running
from ..schemas import ReprocessStartRequest, ReprocessStartResponse, ReprocessStatusResponse
from ..celery_app import celery_app
from ..tasks import reprocess_applications


router = APIRouter(prefix="/api/reprocess", tags=["Reprocess"])


@router.post("/start", response_model=ReprocessStartResponse)
async def start_reprocess(
    body: ReprocessStartRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user_required),
):
    task = reprocess_applications.delay(
        current_user.id,
        only_needs_review=body.only_needs_review,
        min_confidence=body.min_confidence,
        limit=body.limit,
        batch_size=body.batch_size,
        dry_run=body.dry_run,
    )
    # Mark queued immediately so the UI can show state even before worker picks it up.
    set_reprocess_state_running(
        db,
        user_id=current_user.id,
        total=0,
        message="Queued…",
        task_id=task.id,
        params=body.model_dump(),
    )
    return ReprocessStartResponse(task_id=task.id, status="queued")


@router.get("/status", response_model=ReprocessStatusResponse)
async def reprocess_status(
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user_required),
):
    row = get_reprocess_state(db, current_user.id)
    if not row:
        return ReprocessStatusResponse()

    celery_state = None
    if row.task_id:
        try:
            celery_state = AsyncResult(row.task_id, app=celery_app).state
        except Exception:
            celery_state = None

    return ReprocessStatusResponse(
        status=row.status or "idle",
        message=(row.message or "").strip(),
        processed=int(row.processed or 0),
        total=int(row.total or 0),
        error=row.error,
        task_id=row.task_id,
        params=row.params,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
        celery_state=celery_state,
    )

