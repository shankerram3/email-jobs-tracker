"""Celery tasks: email sync (incremental/full). DB session per task; state in DB."""
from datetime import datetime
from typing import Optional
from celery import shared_task
from sqlalchemy.orm import Session

from .database import SessionLocal
from .sync_state_db import get_sync_state, set_sync_state_syncing, set_sync_state_idle, set_sync_state_error
from .services.email_processor import run_sync_with_options
from .reprocess_state_db import (
    set_reprocess_state_running,
    update_reprocess_progress,
    set_reprocess_state_idle as set_reprocess_idle,
    set_reprocess_state_error as set_reprocess_error,
)
from .services.reprocess_service import ReprocessOptions, run_reprocess_applications


@shared_task(bind=True, name="app.tasks.run_email_sync")
def run_email_sync(
    self,
    mode: str = "incremental",
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """
    Run email sync. mode: incremental | full.
    after_date: optional YYYY-MM-DD or YYYY/MM/DD for full sync "from" date.
    before_date: optional YYYY-MM-DD or YYYY/MM/DD for full sync "to" date.
    Uses DB session per task; updates sync_state in DB for resilience to restarts.
    """
    db = SessionLocal()
    try:
        if user_id is None:
            raise ValueError("user_id is required for multi-user sync tasks")
        set_sync_state_syncing(db, user_id=user_id)
        progress_callback = None  # Celery task can't push to SSE; progress stored in sync_state
        result = run_sync_with_options(
            db,
            mode=mode,
            on_progress=progress_callback,
            after_date=after_date,
            before_date=before_date,
            user_id=user_id,
        )
        if result.get("error"):
            set_sync_state_error(db, result["error"], user_id=user_id)
        else:
            set_sync_state_idle(db, result, user_id=user_id)
    except Exception as e:
        try:
            set_sync_state_error(db, str(e), user_id=user_id)
        except Exception:
            pass
        raise
    finally:
        db.close()
    return result


@shared_task(bind=True, name="app.tasks.reprocess_applications")
def reprocess_applications(
    self,
    user_id: int,
    only_needs_review: bool = True,
    min_confidence: Optional[float] = None,
    limit: int = 500,
    batch_size: int = 25,
    dry_run: bool = False,
):
    """
    Re-run LangGraph classification+extraction for existing applications in DB.
    Stores progress in reprocess_state table for polling via API.
    """
    db = SessionLocal()
    task_id = getattr(getattr(self, "request", None), "id", None)
    try:
        # We don't know total until we query; set placeholder total=0 and update as we go.
        params = {
            "only_needs_review": only_needs_review,
            "min_confidence": min_confidence,
            "limit": limit,
            "batch_size": batch_size,
            "dry_run": dry_run,
        }
        set_reprocess_state_running(db, user_id=user_id, total=0, task_id=task_id, params=params)

        def on_progress(processed: int, total: int, message: str):
            update_reprocess_progress(db, user_id=user_id, processed=processed, total=total, message=message)

        result = run_reprocess_applications(
            db,
            user_id=user_id,
            options=ReprocessOptions(
                only_needs_review=only_needs_review,
                min_confidence=min_confidence,
                limit=limit,
                batch_size=batch_size,
                dry_run=dry_run,
            ),
            on_progress=on_progress,
        )
        set_reprocess_idle(db, user_id=user_id, result=result)
        return result
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        set_reprocess_error(db, user_id=user_id, error=str(e))
        raise
    finally:
        db.close()
