"""Auth API: email/password login, Sign in with Google (OAuth), JWT response, /me."""
import secrets
import urllib.parse
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import httpx

from ..oauth_state_db import KIND_GOOGLE_LOGIN, oauth_state_set, oauth_state_consume
from ..auth import (
    create_access_token,
    get_current_user,
    get_current_user_required,
    verify_password,
    hash_password,
    get_user_by_email,
)
from ..database import get_db
from ..models import User
from ..config import settings

router = APIRouter(prefix="/api", tags=["auth"])

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = ["openid", "email", "profile"]


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: Optional[str] = None


class MeResponse(BaseModel):
    email: str
    id: int
    name: Optional[str] = None
    has_password: bool = False  # True if user can change password (email/password account)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _google_redirect_uri() -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    return "http://localhost:8000/api/auth/google/callback"


@router.post("/login", response_model=TokenResponse)
def login_email_password(req: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password. Returns JWT. Requires SECRET_KEY."""
    if not settings.secret_key:
        raise HTTPException(status_code=500, detail="SECRET_KEY not set")
    user = get_user_by_email(db, req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail="This account uses Sign in with Google. Use the Google button to sign in.",
        )
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, email=user.email)


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user_required)):
    """Return current user (email, id, name, has_password). Requires auth."""
    return MeResponse(
        email=current_user.email,
        id=current_user.id,
        name=current_user.name,
        has_password=bool(current_user.password_hash),
    )


@router.post("/me/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """Change password. Requires current password. Only for accounts with a password (not Google-only)."""
    if not current_user.password_hash:
        raise HTTPException(
            status_code=400,
            detail="This account uses Sign in with Google. Set a password in your Google account instead.",
        )
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    current_user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"message": "Password updated successfully"}


@router.get("/auth/google")
def google_auth_start(redirect_url: Optional[str] = None):
    """Redirect to Google Sign-in. Frontend should link to this or redirect here."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_ID not set. Add it to .env for Sign in with Google.",
        )
    redirect_uri = _google_redirect_uri()
    frontend_origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
    after_login = redirect_url or frontend_origin
    state = secrets.token_urlsafe(32)
    oauth_state_set(KIND_GOOGLE_LOGIN, state, after_login)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@router.get("/auth/google/callback")
def google_auth_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Exchange code for tokens, get userinfo, find or create user, redirect to frontend with JWT."""
    if error:
        # Redirect to frontend with error (e.g. user denied)
        frontend_origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
        return RedirectResponse(url=f"{frontend_origin}/login?error=access_denied", status_code=302)
    if not state:
        frontend_origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
        return RedirectResponse(url=f"{frontend_origin}/login?error=missing_state", status_code=302)
    entry = oauth_state_consume(state)
    if not entry:
        frontend_origin = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
        return RedirectResponse(url=f"{frontend_origin}/login?error=invalid_state", status_code=302)
    if not code or not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=400, detail="Missing code or Google OAuth config")

    redirect_uri = _google_redirect_uri()

    # Exchange code for tokens
    try:
        with httpx.Client() as client:
            r = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            token_response = r.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    if "error" in token_response:
        raise HTTPException(status_code=400, detail=token_response.get("error_description", "Token exchange failed"))

    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in response")

    # Get userinfo
    def _userinfo():
        with httpx.Client() as client:
            r = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()

    try:
        userinfo = _userinfo()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Userinfo failed: {e}")

    google_id = userinfo.get("id")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name")

    if not email:
        raise HTTPException(status_code=400, detail="Google did not return an email")

    # Find or create user
    user = get_user_by_email(db, email)
    if user:
        if not user.google_id:
            user.google_id = google_id
            user.name = user.name or name
            db.commit()
            db.refresh(user)
    else:
        user = User(
            email=email,
            google_id=google_id,
            name=name,
            password_hash=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not settings.secret_key:
        raise HTTPException(status_code=500, detail="SECRET_KEY not set")
    token = create_access_token(user.id, user.email)

    # Redirect to frontend with token in fragment (so it isn't sent to server logs)
    frontend_origin = entry.get("redirect_url") or (settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173")
    return RedirectResponse(url=f"{frontend_origin}/login#token={token}", status_code=302)
