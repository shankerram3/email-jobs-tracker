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


def set_sync_state_syncing(db: Session, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    if row:
        row.status = "syncing"
        row.error = None
        row.updated_at = now
    else:
        db.add(SyncState(user_id=user_id, status="syncing", updated_at=now))
    db.commit()


def set_sync_state_idle(db: Session, result: dict, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    if row:
        row.status = "idle"
        row.error = result.get("error")
        row.last_synced_at = now
        if result.get("full_sync"):
            row.last_full_sync_at = now
        row.updated_at = now
    else:
        db.add(SyncState(user_id=user_id, status="idle", last_synced_at=now, updated_at=now))
    db.commit()


def set_sync_state_error(db: Session, error: str, user_id: Optional[int] = None):
    now = datetime.utcnow()
    row = get_sync_state(db, user_id)
    if row:
        row.status = "error"
        row.error = error
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
