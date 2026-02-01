"""API auth: JWT (email/password or Google OAuth) or API key. Returns User for protected routes."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Query
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import User

import bcrypt


class TokenData(BaseModel):
    sub: Optional[str] = None  # user_id
    email: Optional[str] = None
    exp: Optional[datetime] = None


api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, email: Optional[str] = None) -> str:
    if not settings.secret_key:
        raise ValueError("SECRET_KEY not set")
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode = {"sub": str(user_id), "email": email, "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> Optional[TokenData]:
    if not settings.secret_key:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        email = payload.get("email")
        exp = payload.get("exp")
        if exp:
            exp = datetime.utcfromtimestamp(exp)
        return TokenData(sub=sub, email=email, exp=exp)
    except JWTError:
        return None


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[User]:
    """Validate JWT or API key. Returns User or None if auth disabled."""
    # API key: map to configured user or first user (backward compat)
    if settings.api_key and api_key and api_key == settings.api_key:
        if settings.api_key_user_id is not None:
            user = await get_user_by_id(db, settings.api_key_user_id)
            if user:
                return user
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key user not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        result = await db.execute(select(User).order_by(User.id).limit(1))
        user = result.scalars().first()
        if user:
            return user
    # JWT
    if credentials and credentials.credentials:
        data = verify_token(credentials.credentials)
        if data and data.sub:
            try:
                uid = int(data.sub)
                user = await get_user_by_id(db, uid)
                if user:
                    return user
            except ValueError:
                pass
    # No auth configured: allow anonymous (backward compatible)
    if not settings.secret_key and not settings.api_key:
        return None
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_required(
    current_user: Optional[User] = Depends(get_current_user),
) -> User:
    """Require a logged-in user; 401 if not."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_user_for_sse(
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """Auth for SSE: accept JWT from ?token= (EventSource can't set headers) or Bearer/API key. 401 if not authenticated."""
    if token:
        data = verify_token(token)
        if data and data.sub:
            try:
                uid = int(data.sub)
                user = await get_user_by_id(db, uid)
                if user:
                    return user
            except ValueError:
                pass
    current = await get_current_user(db=db, credentials=credentials, api_key=api_key)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current
