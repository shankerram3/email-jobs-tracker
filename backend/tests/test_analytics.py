"""Integration tests for analytics endpoints."""
import pytest
from datetime import datetime, timedelta, timezone

from app.models import Application, User
from app.database import get_db
from app.auth import get_current_user_required


def _make_test_user(db_session):
    """Create a test user and return it (committed)."""
    user = User(email="test@analytics.test", password_hash=None)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _override_auth_and_db(app, db_session, user):
    """Override get_db and get_current_user_required for authenticated analytics tests."""
    def override_get_db():
        yield db_session

    async def override_get_current_user_required():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_required] = override_get_current_user_required


def test_analytics_funnel(client, db_session):
    """GET /api/analytics/funnel returns funnel stages."""
    from app.main import app
    user = _make_test_user(db_session)
    for i, cat in enumerate(["REJECTION", "INTERVIEW_REQUEST", "OFFER"]):
        db_session.add(Application(
            gmail_message_id=f"msg{i}",
            user_id=user.id,
            company_name=f"Co{i}",
            status="APPLIED",
            category=cat,
            email_subject="Subj",
            email_from="from@x.com",
            received_date=datetime.now(timezone.utc),
        ))
    db_session.commit()
    _override_auth_and_db(app, db_session, user)
    try:
        r = client.get("/api/analytics/funnel")
        assert r.status_code == 200
        data = r.json()
        assert "funnel" in data
        assert data["total"] >= 3
        stages = {s["stage"]: s for s in data["funnel"]}
        assert "Applied" in stages
        assert "Rejection" in stages
    finally:
        app.dependency_overrides.clear()


def test_analytics_response_rate(client, db_session):
    """GET /api/analytics/response-rate returns items."""
    from app.main import app
    user = _make_test_user(db_session)
    _override_auth_and_db(app, db_session, user)
    try:
        r = client.get("/api/analytics/response-rate?group_by=company")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert data["group_by"] == "company"
    finally:
        app.dependency_overrides.clear()


def test_analytics_time_to_event(client, db_session):
    """GET /api/analytics/time-to-event returns median/avg."""
    from app.main import app
    user = _make_test_user(db_session)
    _override_auth_and_db(app, db_session, user)
    try:
        r = client.get("/api/analytics/time-to-event?event=rejection")
        assert r.status_code == 200
        data = r.json()
        assert "event" in data
        assert "sample_size" in data
    finally:
        app.dependency_overrides.clear()


def test_analytics_prediction(client, db_session):
    """GET /api/analytics/prediction returns items or empty."""
    from app.main import app
    user = _make_test_user(db_session)
    _override_auth_and_db(app, db_session, user)
    try:
        r = client.get("/api/analytics/prediction?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "limit" in data
    finally:
        app.dependency_overrides.clear()
