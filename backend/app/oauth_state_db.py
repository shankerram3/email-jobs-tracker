"""OAuth CSRF state persisted in DB (Gmail and Google Sign-in)."""
from datetime import datetime
from typing import Optional

from .database import SessionLocal
from .models import OAuthState

OAUTH_STATE_TTL_SECONDS = 900  # 15 minutes (avoids invalid_state when slow or callback retried)

KIND_GMAIL = "gmail"
KIND_GOOGLE_LOGIN = "google_login"


def oauth_state_set(kind: str, state_token: str, redirect_url: Optional[str] = None) -> None:
    """Store OAuth state token. Overwrites if exists."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        row = db.query(OAuthState).filter(OAuthState.state_token == state_token).first()
        if row:
            row.kind = kind
            row.redirect_url = redirect_url
            row.created_at = now
        else:
            db.add(OAuthState(
                state_token=state_token,
                kind=kind,
                redirect_url=redirect_url or "",
                created_at=now,
            ))
        db.commit()
    finally:
        db.close()


def oauth_state_consume(state_token: str) -> Optional[dict]:
    """
    Look up state, validate TTL, delete row, return payload or None.
    Returns {"redirect_url": str, "created_at": datetime} if valid; None if missing or expired.
    """
    db = SessionLocal()
    try:
        row = db.query(OAuthState).filter(OAuthState.state_token == state_token).first()
        if not row:
            return None
        if (datetime.utcnow() - row.created_at).total_seconds() > OAUTH_STATE_TTL_SECONDS:
            db.delete(row)
            db.commit()
            return None
        payload = {"redirect_url": row.redirect_url or "", "created_at": row.created_at}
        db.delete(row)
        db.commit()
        return payload
    finally:
        db.close()


def oauth_state_cleanup_expired() -> None:
    """Delete expired state rows."""
    db = SessionLocal()
    try:
        rows = db.query(OAuthState).all()
        for row in rows:
            if (datetime.utcnow() - row.created_at).total_seconds() > OAUTH_STATE_TTL_SECONDS:
                db.delete(row)
        db.commit()
    finally:
        db.close()
