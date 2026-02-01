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

    def capture_fetch_parallel(service, queries, max_results_per_query=100, max_workers=7, on_progress=None, **kwargs):
        captured_queries.extend(queries)
        return []

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails_parallel", side_effect=capture_fetch_parallel),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
    ):
        run_sync_with_options(db, mode="full", after_date="2024-01-15")

    assert len(captured_queries) > 0
    # Normalized date is YYYY/MM/DD
    assert any("2024/01/15" in q for q in captured_queries)


def test_full_sync_uses_after_date_iso_format(db):
    """after_date YYYY-MM-DD is normalized to YYYY/MM/DD in queries."""
    captured_queries = []

    def capture_fetch_parallel(service, queries, max_results_per_query=100, max_workers=7, on_progress=None, **kwargs):
        captured_queries.extend(queries)
        return []

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails_parallel", side_effect=capture_fetch_parallel),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
    ):
        run_sync_with_options(db, mode="full", after_date="2025-06-01")

    assert any("2025/06/01" in q for q in captured_queries)


def test_full_sync_uses_before_date_in_queries(db):
    """run_sync_with_options with before_date set includes before: in Gmail queries."""
    captured_queries = []

    def capture_fetch_parallel(service, queries, max_results_per_query=100, max_workers=7, on_progress=None, **kwargs):
        captured_queries.extend(queries)
        return []

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails_parallel", side_effect=capture_fetch_parallel),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
    ):
        run_sync_with_options(db, mode="full", after_date="2024-01-01", before_date="2024-06-30")

    assert len(captured_queries) > 0
    assert any("2024/01/01" in q and "before:2024/06/30" in q for q in captured_queries)


def test_classification_creates_application_on_cache_miss(db):
    """With one email from Gmail and cache miss, LangGraph result is persisted and Application created."""
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

    def return_one_email_parallel(service, queries, max_results_per_query=100, max_workers=7, on_progress=None, **kwargs):
        return [one_email]

    langgraph_result = {
        "email_class": "interview_assessment",
        "company_name": "Acme",
        "job_title": "Software Engineer",
        "position_level": "Mid",
        "confidence": 0.9,
        "classification_reasoning": "Scheduling / assessment email.",
        "application_stage": "Screening",
        "requires_action": True,
        "action_items": ["Complete assessment or schedule interview"],
        "processing_status": "completed",
        "errors": [],
    }

    mock_service = MagicMock()
    with (
        patch("app.services.email_processor.get_gmail_service", return_value=mock_service),
        patch("app.services.email_processor.fetch_emails_parallel", side_effect=return_one_email_parallel),
        patch("app.services.email_processor.get_profile_history_id", return_value="hist1"),
        patch("app.services.email_processor._get_cached_langgraph_state", return_value=None),
        patch("app.services.email_processor.langgraph_process_batch", return_value=[langgraph_result]),
        patch("app.services.email_processor.langgraph_process_email", return_value=langgraph_result),
    ):
        result = run_sync_with_options(db, mode="full")

    assert result.get("error") is None
    assert result.get("created") == 1
    assert db.query(Application).count() == 1
    assert db.query(EmailLog).count() == 1
    app = db.query(Application).first()
    assert app.company_name == "Acme"
    assert app.category == "interview_assessment"
    assert app.application_stage == "Screening"
    assert app.status == "INTERVIEWING"
