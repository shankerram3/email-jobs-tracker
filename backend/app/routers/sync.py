"""Email sync API."""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..services.email_processor import run_sync
from ..sync_state import set_syncing, update_progress, set_idle, set_error, get_state

router = APIRouter(prefix="/api", tags=["sync"])


def task():
    session = SessionLocal()
    try:
        def on_progress(processed: int, total: int, message: str):
            update_progress(processed, total, message)

        set_syncing(total=0)
        result = run_sync(session, on_progress=on_progress)
        if result.get("error"):
            set_error(result["error"])
        else:
            set_idle(result)
    except Exception as e:
        set_error(str(e))
    finally:
        session.close()


@router.post("/sync-emails")
async def sync_emails(background_tasks: BackgroundTasks):
    """Start email sync in background. Poll GET /api/sync-status for progress."""
    background_tasks.add_task(task)
    return {"message": "Email sync started.", "status": "syncing"}


@router.get("/sync-status")
def sync_status():
    """Current sync progress: status (idle | syncing), message, processed, total, created, skipped, errors, error."""
    return get_state()
