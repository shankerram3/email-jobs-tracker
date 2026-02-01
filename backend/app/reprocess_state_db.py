"""DB-backed state for batch reprocessing of existing applications."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import ReprocessState


def get_reprocess_state(db: Session, user_id: int) -> Optional[ReprocessState]:
    return (
        db.query(ReprocessState)
        .filter(ReprocessState.user_id == user_id)
        .order_by(ReprocessState.id.desc())
        .first()
    )


def set_reprocess_state_running(
    db: Session,
    *,
    user_id: int,
    total: int,
    message: str = "Starting…",
    task_id: Optional[str] = None,
    params: Optional[dict[str, Any]] = None,
) -> None:
    now = datetime.utcnow()
    row = get_reprocess_state(db, user_id)
    if row:
        row.status = "running"
        row.error = None
        row.message = message
        row.processed = 0
        row.total = int(total or 0)
        row.task_id = task_id
        row.params = params or {}
        row.started_at = now
        row.finished_at = None
        row.updated_at = now
    else:
        db.add(
            ReprocessState(
                user_id=user_id,
                status="running",
                message=message,
                processed=0,
                total=int(total or 0),
                task_id=task_id,
                params=params or {},
                started_at=now,
                updated_at=now,
            )
        )
    db.commit()


def update_reprocess_progress(
    db: Session,
    *,
    user_id: int,
    processed: int,
    total: int,
    message: str,
) -> None:
    now = datetime.utcnow()
    row = get_reprocess_state(db, user_id)
    if not row:
        # Create a row to avoid losing progress.
        db.add(
            ReprocessState(
                user_id=user_id,
                status="running",
                message=message or "",
                processed=int(processed or 0),
                total=int(total or 0),
                started_at=now,
                updated_at=now,
            )
        )
    else:
        row.status = "running"
        row.message = (message or "")[:255]
        row.processed = int(processed or 0)
        row.total = int(total or 0)
        row.updated_at = now
    db.commit()


def set_reprocess_state_idle(db: Session, *, user_id: int, result: dict[str, Any]) -> None:
    now = datetime.utcnow()
    row = get_reprocess_state(db, user_id)
    processed = int(result.get("processed", 0) or 0)
    total = int(result.get("total", processed) or processed)
    if row:
        row.status = "idle"
        row.error = None
        row.message = "Done"
        row.processed = processed
        row.total = total
        row.finished_at = now
        row.updated_at = now
    else:
        db.add(
            ReprocessState(
                user_id=user_id,
                status="idle",
                message="Done",
                processed=processed,
                total=total,
                started_at=now,
                finished_at=now,
                updated_at=now,
            )
        )
    db.commit()


def set_reprocess_state_error(db: Session, *, user_id: int, error: str) -> None:
    now = datetime.utcnow()
    row = get_reprocess_state(db, user_id)
    if row:
        row.status = "error"
        row.error = error
        row.message = ""
        row.finished_at = now
        row.updated_at = now
    else:
        db.add(
            ReprocessState(
                user_id=user_id,
                status="error",
                error=error,
                message="",
                started_at=now,
                finished_at=now,
                updated_at=now,
            )
        )
    db.commit()

