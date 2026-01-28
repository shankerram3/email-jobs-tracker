"""Application configuration."""
import os
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
