"""Tests for multi-user isolation on /api/langgraph/* endpoints."""

from datetime import datetime, timezone

from app.models import Application, User
from app.auth import get_current_user_required
from app.database import get_sync_db


def _make_user(db_session, email: str) -> User:
    user = User(email=email, password_hash=None)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _override_auth(app, user: User):
    async def override_get_current_user_required():
        return user

    app.dependency_overrides[get_current_user_required] = override_get_current_user_required


def _override_sync_db(app, db_session):
    def override_get_sync_db():
        yield db_session

    app.dependency_overrides[get_sync_db] = override_get_sync_db


def test_langgraph_action_required_is_user_scoped(client, db_session):
    from app.main import app

    user_a = _make_user(db_session, "a@multi.test")
    user_b = _make_user(db_session, "b@multi.test")

    # A has two action-required apps; B has one.
    db_session.add_all(
        [
            Application(
                gmail_message_id="a1",
                user_id=user_a.id,
                company_name="Aco",
                status="APPLIED",
                category="interview_assessment",
                application_stage="Interview",
                requires_action=True,
                action_items=["Do thing A1"],
                email_subject="Subj",
                email_from="from@x.com",
                received_date=datetime.now(timezone.utc),
            ),
            Application(
                gmail_message_id="a2",
                user_id=user_a.id,
                company_name="Aco2",
                status="APPLIED",
                category="interview_assessment",
                application_stage="Interview",
                requires_action=True,
                action_items=["Do thing A2"],
                email_subject="Subj",
                email_from="from@x.com",
                received_date=datetime.now(timezone.utc),
            ),
            Application(
                gmail_message_id="b1",
                user_id=user_b.id,
                company_name="Bco",
                status="APPLIED",
                category="interview_assessment",
                application_stage="Interview",
                requires_action=True,
                action_items=["Do thing B1"],
                email_subject="Subj",
                email_from="from@x.com",
                received_date=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    _override_auth(app, user_b)
    _override_sync_db(app, db_session)
    try:
        r = client.get("/api/langgraph/action-required?limit=10")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["gmail_message_id"] == "b1"
        assert items[0]["company_name"] == "Bco"
    finally:
        app.dependency_overrides.clear()


def test_langgraph_analytics_is_user_scoped(client, db_session):
    from app.main import app

    user_a = _make_user(db_session, "a2@multi.test")
    user_b = _make_user(db_session, "b2@multi.test")

    db_session.add_all(
        [
            Application(
                gmail_message_id="a1",
                user_id=user_a.id,
                company_name="Aco",
                status="APPLIED",
                category="job_rejection",
                confidence=0.1,
                application_stage="Rejected",
                requires_action=False,
                email_subject="Subj",
                email_from="from@x.com",
                received_date=datetime.now(timezone.utc),
            ),
            Application(
                gmail_message_id="b1",
                user_id=user_b.id,
                company_name="Bco",
                status="APPLIED",
                category="interview_assessment",
                confidence=0.9,
                application_stage="Interview",
                requires_action=True,
                action_items=["Do thing"],
                email_subject="Subj",
                email_from="from@x.com",
                received_date=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    _override_auth(app, user_b)
    _override_sync_db(app, db_session)
    try:
        r = client.get("/api/langgraph/analytics")
        assert r.status_code == 200
        data = r.json()
        assert data["total_processed"] == 1
        assert data["action_required_count"] == 1
        # Ensure it doesn't count A's rejection stage
        assert data["by_stage"].get("Rejected", 0) == 0
    finally:
        app.dependency_overrides.clear()


def test_langgraph_requires_auth(client):
    # Without overriding auth, these endpoints should require authentication.
    r = client.get("/api/langgraph/action-required")
    assert r.status_code == 401

