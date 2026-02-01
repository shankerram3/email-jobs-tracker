"""Email sync API: POST sync with mode, GET sync-status, GET sync-events (SSE), Gmail OAuth."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

from ..database import SessionLocal, get_sync_db
from ..services.email_processor import run_sync_with_options
from ..sync_state import get_state, set_syncing, update_progress, set_idle, set_error
from ..sync_state_db import (
    set_sync_state_syncing,
    set_sync_state_idle,
    set_sync_state_error,
    set_sync_progress,
    get_state_from_db,
)
from ..auth import get_current_user_required, get_current_user_for_sse
from ..models import User
from ..config import settings
from ..gmail_service import (
    get_gmail_service,
    GmailAuthRequiredError,
    _gmail_creds_ready_for_background,
    start_gmail_oauth,
    finish_gmail_oauth,
)

router = APIRouter(prefix="/api", tags=["sync"])


def _run_sync_task(mode: str, user_id: int, after_date: Optional[str] = None, before_date: Optional[str] = None):
    session = SessionLocal()
    try:
        def on_progress(processed: int, total: int, message: str):
            update_progress(processed, total, message, user_id)
            set_sync_progress(session, user_id, processed, total, message)

        set_syncing(total=0, user_id=user_id)
        set_sync_state_syncing(session, user_id)
        result = run_sync_with_options(
            session, mode=mode, on_progress=on_progress, user_id=user_id,
            after_date=after_date, before_date=before_date
        )
        if result.get("error"):
            set_error(result["error"], user_id)
            set_sync_state_error(session, result["error"], user_id)
        else:
            set_idle(result, user_id)
            set_sync_state_idle(session, result, user_id)
    except GmailAuthRequiredError as e:
        set_error(str(e), user_id)
        set_sync_state_error(session, str(e), user_id)
    except Exception as e:
        set_error(str(e), user_id)
        set_sync_state_error(session, str(e), user_id)
    finally:
        session.close()


@router.get("/gmail/auth")
def gmail_auth(redirect_url: Optional[str] = None):
    """
    Complete Gmail OAuth in the browser. Open this URL in your browser to sign in;
    after that, Sync will work without blocking. Optional: ?redirect_url=http://localhost:5173
    When GMAIL_OAUTH_REDIRECT_URI is set, uses CSRF state; add GET /api/gmail/callback as redirect URI in Google Cloud.
    """
    redirect_after = redirect_url or "http://localhost:5173"
    try:
        if settings.gmail_oauth_redirect_uri:
            auth_url = start_gmail_oauth(redirect_url_after=redirect_after)
            return RedirectResponse(url=auth_url, status_code=302)
        get_gmail_service(allow_interactive_oauth=True)
    except FileNotFoundError as e:
        return {"error": str(e), "hint": "Add credentials.json from Google Cloud Console to the backend folder."}
    except ValueError as e:
        return {"error": str(e)}
    return RedirectResponse(url=redirect_after, status_code=302)


@router.get("/gmail/callback")
def gmail_callback(code: Optional[str] = None, state: Optional[str] = None):
    """
    OAuth callback when GMAIL_OAUTH_REDIRECT_URI is set. Validates state and exchanges code for token.
    """
    if not code or not state:
        return {"error": "Missing code or state"}
    try:
        redirect_url = finish_gmail_oauth(code=code, state=state)
        return RedirectResponse(url=redirect_url, status_code=302)
    except ValueError as e:
        return {"error": str(e)}


@router.post("/sync-emails")
async def sync_emails(
    background_tasks: BackgroundTasks,
    mode: Optional[str] = "auto",
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    current_user: User = Depends(get_current_user_required),
):
    """Start email sync. mode=auto|incremental|full. Optional after_date/before_date (YYYY-MM-DD or YYYY/MM/DD) for full sync date range. Poll GET /api/sync-status or GET /api/sync-events for progress."""
    if mode not in ("auto", "incremental", "full"):
        mode = "auto"
    if not _gmail_creds_ready_for_background():
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Gmail authorization required. Open /api/gmail/auth in your browser to sign in, then try Sync again.",
        )
    background_tasks.add_task(_run_sync_task, mode, current_user.id, after_date, before_date)
    return {"message": "Email sync started.", "status": "syncing", "mode": mode, "after_date": after_date, "before_date": before_date}


@router.get("/sync-status")
def sync_status(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_sync_db),
):
    """Current sync progress for this user: status, message, processed, total, created, skipped, errors, error."""
    return get_state_from_db(db, current_user.id)


async def _sse_generator(user_id: int):
    """Yield SSE events with sync progress for this user until status is idle or error."""
    while True:
        session = SessionLocal()
        try:
            state = get_state_from_db(session, user_id)
        finally:
            session.close()
        data = json.dumps(state)
        yield {"data": data}
        if state.get("status") in ("idle", "error"):
            break
        await asyncio.sleep(0.5)


@router.get("/sync-events")
async def sync_events(
    current_user: User = Depends(get_current_user_for_sse),
):
    """SSE stream of sync progress for this user. Pass ?token=JWT in URL when using EventSource (browser cannot set Authorization header)."""
    return EventSourceResponse(_sse_generator(current_user.id))
