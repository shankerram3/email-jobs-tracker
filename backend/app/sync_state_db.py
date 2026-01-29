"""Sync state in DB (SyncState model) per user. In-memory state for SSE progress."""
from datetime import datetime
from typing import Optional
import threading
from sqlalchemy.orm import Session

from .models import SyncState

# In-memory progress for SSE (processed, total, message)
_memory = {
    "processed": 0,
    "total": 0,
    "message": "",
}
_lock = threading.Lock()


def get_sync_state(db: Session, user_id: Optional[int] = None) -> Optional[SyncState]:
    q = db.query(SyncState)
    if user_id is not None:
        q = q.filter(SyncState.user_id == user_id)
    return q.order_by(SyncState.id.desc()).first()


def get_last_history_id(db: Session, user_id: Optional[int] = None) -> Optional[str]:
    row = get_sync_state(db, user_id)
    return row.last_history_id if row else None


def set_last_history_id(db: Session, history_id: str, user_id: Optional[int] = None):
    row = get_sync_state(db, user_id)
    now = datetime.utcnow()
    if row:
        row.last_history_id = history_id
        row.last_synced_at = now
        row.updated_at = now
    else:
        db.add(SyncState(user_id=user_id, last_history_id=history_id, last_synced_at=now, status="idle"))
    db.commit()


def set_last_full_sync_at(db: Session, user_id: Optional[int] = None):
    """Update per-user SyncState with last_full_sync_at (for full-sync window)."""
    if user_id is None:
        return
    row = get_sync_state(db, user_id)
    now = datetime.utcnow()
    if row:
        row.last_full_sync_at = now
        row.updated_at = now
        db.commit()
    else:
        db.add(SyncState(user_id=user_id, last_full_sync_at=now, status="idle", updated_at=now))
        db.commit()


def set_sync_state_syncing(db: Session, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    if row:
        row.status = "syncing"
        row.error = None
        row.processed = 0
        row.total = 0
        row.message = "Connecting to Gmail…"
        row.updated_at = now
    else:
        db.add(SyncState(
            user_id=user_id, status="syncing", processed=0, total=0, message="Connecting to Gmail…", updated_at=now
        ))
    db.commit()


def set_sync_progress(db: Session, user_id: Optional[int], processed: int, total: int, message: str):
    """Persist sync progress (processed, total, message) to DB for this user."""
    if user_id is None:
        return
    row = get_sync_state(db, user_id)
    now = datetime.utcnow()
    if row:
        row.processed = processed
        row.total = total
        row.message = message or ""
        row.updated_at = now
    else:
        db.add(SyncState(
            user_id=user_id, status="syncing", processed=processed, total=total, message=message or "", updated_at=now
        ))
    db.commit()


def get_state_from_db(db: Session, user_id: Optional[int] = None) -> dict:
    """Return sync state dict (same shape as get_state) from DB. Used by GET /sync-status and SSE."""
    default = {
        "status": "idle",
        "message": "",
        "processed": 0,
        "total": 0,
        "created": 0,
        "skipped": 0,
        "errors": 0,
        "error": None,
    }
    if user_id is None:
        return default
    row = get_sync_state(db, user_id)
    if not row:
        return default
    return {
        "status": row.status or "idle",
        "message": (row.message or "").strip(),
        "processed": row.processed if row.processed is not None else 0,
        "total": row.total if row.total is not None else 0,
        "created": row.created if row.created is not None else 0,
        "skipped": row.skipped if row.skipped is not None else 0,
        "errors": row.errors if row.errors is not None else 0,
        "error": row.error,
    }


def set_sync_state_idle(db: Session, result: dict, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    processed = result.get("processed", 0)
    if row:
        row.status = "idle"
        row.error = result.get("error")
        row.processed = processed
        row.total = processed
        row.message = "Done"
        row.created = result.get("created", 0)
        row.skipped = result.get("skipped", 0)
        row.errors = result.get("errors", 0)
        row.last_synced_at = now
        if result.get("full_sync"):
            row.last_full_sync_at = now
        row.updated_at = now
    else:
        db.add(SyncState(
            user_id=user_id,
            status="idle",
            last_synced_at=now,
            processed=processed,
            total=processed,
            message="Done",
            created=result.get("created", 0),
            skipped=result.get("skipped", 0),
            errors=result.get("errors", 0),
            updated_at=now,
        ))
    db.commit()


def set_sync_state_error(db: Session, error: str, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    if row:
        row.status = "error"
        row.error = error
        row.message = ""
        row.updated_at = now
    else:
        db.add(SyncState(user_id=user_id, status="error", error=error, updated_at=now))
    db.commit()


def get_memory_progress() -> dict:
    with _lock:
        return dict(_memory)


def set_memory_progress(processed: int, total: int, message: str):
    with _lock:
        _memory["processed"] = processed
        _memory["total"] = total
        _memory["message"] = message
