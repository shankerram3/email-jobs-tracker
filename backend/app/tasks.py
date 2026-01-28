"""Celery tasks: email sync (incremental/full). DB session per task; state in DB."""
from datetime import datetime
from typing import Optional
from celery import shared_task
from sqlalchemy.orm import Session

from .database import SessionLocal
from .sync_state_db import get_sync_state, set_sync_state_syncing, set_sync_state_idle, set_sync_state_error
from .services.email_processor import run_sync_with_options


@shared_task(bind=True, name="app.tasks.run_email_sync")
def run_email_sync(self, mode: str = "incremental", after_date: Optional[str] = None):
    """
    Run email sync. mode: incremental | full.
    after_date: optional YYYY-MM-DD or YYYY/MM/DD for full sync "from" date.
    Uses DB session per task; updates sync_state in DB for resilience to restarts.
    """
    db = SessionLocal()
    try:
        set_sync_state_syncing(db)
        progress_callback = None  # Celery task can't push to SSE; progress stored in sync_state
        result = run_sync_with_options(
            db, mode=mode, on_progress=progress_callback, after_date=after_date
        )
        if result.get("error"):
            set_sync_state_error(db, result["error"])
        else:
            set_sync_state_idle(db, result)
    except Exception as e:
        set_sync_state_error(db, str(e))
        raise
    finally:
        db.close()
    return result
