"""Application configuration. All sensitive config from .env."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """App settings from environment."""

    # Database - default SQLite for easy local dev; use DATABASE_URL for PostgreSQL
    database_url: str = "sqlite:///./job_tracker.db"

    # Gmail - paths relative to backend/ or set absolute
    credentials_path: str = "credentials.json"
    token_path: str = "token.pickle"

    # AI - set OPENAI_API_KEY for OpenAI classification
    openai_api_key: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Redis (for Celery and optional cache)
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: Optional[str] = None  # defaults to redis_url if not set

    # Auth - JWT or API key (at least one recommended for production)
    secret_key: str = ""  # for JWT signing; set SECRET_KEY in .env
    api_key_header: str = "X-API-Key"
    api_key: str = ""  # optional static API key; set API_KEY in .env
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Google OAuth for "Sign in with Google"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: Optional[str] = None  # e.g. http://localhost:8000/api/auth/google/callback

    # Gmail rate limiting
    gmail_history_max_results: int = 100
    gmail_messages_max_results: int = 100
    gmail_sync_page_size: int = 100  # Increased from 50 for better performance
    # Max emails to fetch per query during full sync (increase if you have many job emails)
    gmail_full_sync_max_per_query: int = 2000
    # Full sync window controls
    # If set, override the full sync "after:" date (YYYY/MM/DD or YYYY-MM-DD)
    gmail_full_sync_after_date: Optional[str] = None
    # Days back for full sync when no override date is set
    gmail_full_sync_days_back: int = 90
    # If true, ignore last_synced_at when doing a full sync (use after_date/days_back)
    gmail_full_sync_ignore_last_synced: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url


settings = Settings()
