"""Tests for sync after_date and classification flow (cache + parallel LLM, create application)."""
import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Application, EmailLog
from app.services.email_processor import run_sync_with_options


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_full_sync_uses_after_date_in_queries(db):
    """run_sync_with_options with after_date set uses that date in full-sync Gmail queries."""
    captured_queries = []

    def capture_fetch(service, query, max_results=100):
        captured_queries.append(query)
        return []

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails", side_effect=capture_fetch),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
    ):
        run_sync_with_options(db, mode="full", after_date="2024-01-15")

    assert len(captured_queries) > 0
    # Normalized date is YYYY/MM/DD
    assert any("2024/01/15" in q for q in captured_queries)


def test_full_sync_uses_after_date_iso_format(db):
    """after_date YYYY-MM-DD is normalized to YYYY/MM/DD in queries."""
    captured_queries = []

    def capture_fetch(service, query, max_results=100):
        captured_queries.append(query)
        return []

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails", side_effect=capture_fetch),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
    ):
        run_sync_with_options(db, mode="full", after_date="2025-06-01")

    assert any("2025/06/01" in q for q in captured_queries)


def test_classification_creates_application_on_cache_miss(db):
    """With one email from Gmail and cache miss, LLM result is persisted and Application created."""
    one_email = {
        "id": "msg-sync-test-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Interview at Acme"},
                {"name": "From", "value": "hr@acme.com"},
                {"name": "Date", "value": "Mon, 01 Jan 2024 12:00:00 +0000"},
            ],
            "body": {"data": None},
            "parts": [{"body": {"data": "aGVsbG8="}, "mimeType": "text/plain"}],
        },
    }

    def return_one_email(service, query, max_results=100):
        return [one_email]

    llm_result = {
        "category": "INTERVIEW_REQUEST",
        "subcategory": "phone_screen",
        "company_name": "Acme",
        "job_title": "Software Engineer",
        "salary_min": None,
        "salary_max": None,
        "location": None,
        "confidence": 0.9,
    }

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails", side_effect=return_one_email),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
        patch("app.services.email_processor.get_cached_classification", return_value=None),
        patch("app.services.email_processor.classify_email_llm_only", return_value=llm_result),
    ):
        result = run_sync_with_options(db, mode="full")

    assert result.get("error") is None
    assert result.get("created") == 1
    assert db.query(Application).count() == 1
    assert db.query(EmailLog).count() == 1
    app = db.query(Application).first()
    assert app.company_name == "Acme"
    assert app.category == "INTERVIEW_REQUEST"
