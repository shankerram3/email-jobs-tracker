"""Database engines and sessions.

- FastAPI request handlers use AsyncSession (asyncpg) for higher concurrency.
- Background workers (Celery, thread-based ingestion, Alembic) use sync Session (psycopg).
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

def _is_sqlite(url: URL) -> bool:
    return url.drivername.startswith("sqlite")


def _is_supabase_host(url: URL) -> bool:
    host = (url.host or "").lower()
    return host.endswith(".supabase.co") or host.endswith(".supabase.com") or "supabase" in host


def _with_driver(url: URL, drivername: str) -> URL:
    """Return a copy of URL with a different drivername."""
    return url.set(drivername=drivername)

def _without_query_param(url: URL, key: str) -> URL:
    """Return a copy of URL without a specific query parameter."""
    q = dict(url.query)
    if key not in q:
        return url
    q.pop(key, None)
    return url.set(query=q)

def _resolve_backend_path(maybe_path: str) -> str:
    p = Path(maybe_path)
    if p.is_absolute():
        return str(p)
    # backend/app/database.py -> backend/
    backend_dir = Path(__file__).resolve().parents[1]
    return str((backend_dir / p).resolve())


raw_url: URL = make_url(settings.database_url)
is_transaction_pooler: bool = (raw_url.port == 6543)

# ----------------------------
# Sync engine/session (workers)
# ----------------------------

# SQLite: NullPool so each thread gets its own connection.
# check_same_thread=False allows different threads to open connections.
sync_connect_args: dict = {}
if _is_sqlite(raw_url):
    # timeout is in seconds at the sqlite driver level.
    timeout_s = max(0.0, float(getattr(settings, "sqlite_busy_timeout_ms", 5000)) / 1000.0)
    sync_connect_args = {"check_same_thread": False, "timeout": timeout_s}
    sync_engine = create_engine(
        raw_url,
        connect_args=sync_connect_args,
        poolclass=NullPool,
    )

    @event.listens_for(sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """
        Improve concurrency characteristics for SQLite.
        - WAL: allows concurrent readers while a writer is active
        - busy_timeout: wait for locks instead of failing immediately
        - synchronous NORMAL: good performance/safety tradeoff for local dev
        """
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute(f"PRAGMA busy_timeout={int(getattr(settings, 'sqlite_busy_timeout_ms', 5000))};")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
        except Exception:
            # Pragmas are best-effort; don't block app start if they fail.
            pass
else:
    # If user provided plain postgresql://..., force psycopg for sync usage.
    sync_url = raw_url
    if sync_url.drivername == "postgresql":
        sync_url = _with_driver(sync_url, "postgresql+psycopg")
    # Supavisor transaction mode does not support prepared statements.
    if is_transaction_pooler:
        sync_connect_args = {"prepare_threshold": None}
    sync_engine = create_engine(
        sync_url,
        connect_args=sync_connect_args,
        pool_pre_ping=True,
        pool_size=max(1, int(getattr(settings, "db_pool_size", 5))),
        max_overflow=max(0, int(getattr(settings, "db_max_overflow", 10))),
        pool_timeout=max(1, int(getattr(settings, "db_pool_timeout_s", 30))),
        pool_recycle=max(0, int(getattr(settings, "db_pool_recycle_s", 1800))),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

# ----------------------------
# Async engine/session (API)
# ----------------------------

async_connect_args: dict = {}
async_url = raw_url
if _is_sqlite(async_url):
    # For tests/local async usage.
    if async_url.drivername == "sqlite":
        async_url = _with_driver(async_url, "sqlite+aiosqlite")
else:
    if async_url.drivername == "postgresql":
        async_url = _with_driver(async_url, "postgresql+asyncpg")
    # Supabase requires SSL; asyncpg uses an SSLContext via connect_args["ssl"].
    if _is_supabase_host(async_url):
        # Prefer system/default trust store, but allow overriding with Supabase CA bundle.
        cafile = getattr(settings, "supabase_ssl_ca_file", None)
        if cafile:
            cafile = _resolve_backend_path(cafile)
            ctx = ssl.create_default_context(cafile=cafile)
            # Some Python/OpenSSL combos reject this CA due to strict X.509 rules
            # (e.g. “CA cert does not include key usage extension”).
            # Relax strict mode while still verifying certificates and hostnames.
            strict_flag = getattr(ssl, "VERIFY_X509_STRICT", None)
            if strict_flag is not None:
                try:
                    ctx.verify_flags &= ~strict_flag
                except Exception:
                    # Best-effort; if flags aren't supported, keep defaults.
                    pass
            async_connect_args["ssl"] = ctx
        else:
            async_connect_args["ssl"] = ssl.create_default_context()
        # asyncpg doesn't support libpq-style URL params like `sslmode=require`.
        # We provide SSL via connect_args, so remove it to avoid:
        # TypeError: connect() got an unexpected keyword argument 'sslmode'
        async_url = _without_query_param(async_url, "sslmode")
    # Supavisor transaction mode does not support prepared statements.
    if is_transaction_pooler:
        async_connect_args["statement_cache_size"] = 0

async_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "connect_args": async_connect_args,
}
if not _is_sqlite(async_url):
    # Pooling args apply to Postgres; sqlite+aiosqlite uses StaticPool in tests.
    async_engine_kwargs.update(
        {
            "pool_size": max(1, int(getattr(settings, "db_pool_size", 5))),
            "max_overflow": max(0, int(getattr(settings, "db_max_overflow", 10))),
            "pool_timeout": max(1, int(getattr(settings, "db_pool_timeout_s", 30))),
            "pool_recycle": max(0, int(getattr(settings, "db_pool_recycle_s", 1800))),
        }
    )

async_engine = create_async_engine(async_url, **async_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)

# ----------------------------
# Helpers
# ----------------------------

def init_db():
    """
    Legacy helper (sync).

    We avoid implicit `create_all()` on Postgres; schema should be managed via Alembic.
    """
    if not _is_sqlite(raw_url):
        return
    from .models import Base
    Base.metadata.create_all(bind=sync_engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session


def get_sync_db() -> Generator:
    """Dependency that yields a sync DB session (workers / special cases)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
