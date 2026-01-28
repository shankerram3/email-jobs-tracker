"""In-memory sync progress state per user (read by GET /api/sync-status and SSE)."""
import threading
from typing import Optional

_DEFAULT_STATE = {
    "status": "idle",
    "message": "",
    "processed": 0,
    "total": 0,
    "created": 0,
    "skipped": 0,
    "errors": 0,
    "error": None,
}

_state_by_user: dict[int, dict] = {}
_lock = threading.Lock()


def _state_for_user(user_id: int) -> dict:
    """Assume caller holds _lock."""
    if user_id not in _state_by_user:
        _state_by_user[user_id] = dict(_DEFAULT_STATE)
    return _state_by_user[user_id]


def get_state(user_id: Optional[int] = None) -> dict:
    """Return current sync state for user. If user_id is None, return default idle state."""
    if user_id is None:
        return dict(_DEFAULT_STATE)
    with _lock:
        state = _state_by_user.get(user_id)
        return dict(state) if state else dict(_DEFAULT_STATE)


def set_syncing(total: int = 0, user_id: Optional[int] = None):
    if user_id is None:
        return
    with _lock:
        s = _state_for_user(user_id)
        s["status"] = "syncing"
        s["message"] = "Connecting to Gmail…" if total == 0 else "Processing…"
        s["processed"] = 0
        s["total"] = total
        s["created"] = 0
        s["skipped"] = 0
        s["errors"] = 0
        s["error"] = None


def update_progress(
    processed: int, total: int, message: str = "Classifying…", user_id: Optional[int] = None
):
    if user_id is None:
        return
    with _lock:
        s = _state_by_user.get(user_id)
        if s:
            s["processed"] = processed
            s["total"] = total
            s["message"] = message


def set_idle(result: dict, user_id: Optional[int] = None):
    if user_id is None:
        return
    with _lock:
        s = _state_by_user.get(user_id)
        if s:
            s["status"] = "idle"
            s["message"] = "Done"
            s["processed"] = result.get("processed", 0)
            s["total"] = result.get("processed", 0)
            s["created"] = result.get("created", 0)
            s["skipped"] = result.get("skipped", 0)
            s["errors"] = result.get("errors", 0)
            s["error"] = result.get("error")


def set_error(err: str, user_id: Optional[int] = None):
    if user_id is None:
        return
    with _lock:
        s = _state_by_user.get(user_id)
        if s:
            s["status"] = "idle"
            s["error"] = err
            s["message"] = ""
