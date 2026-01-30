import json


def test_langgraph_process_email_basic(monkeypatch):
    """
    Full pipeline test with mocked LLM responses (no network).
    """
    from app import langgraph_pipeline as lp

    calls = {"n": 0}

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        # First call is classification, second is entity extraction.
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "email_class": "job_application_confirmation",
                    "confidence": 0.91,
                    "reasoning": "This is an automated application receipt.",
                }
            )
        return json.dumps(
            {
                "company_name": "Google",
                "job_title": "Software Engineer",
                "position_level": "Senior",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    result = lp.process_email(
        email_id="test_123",
        subject="Thank you for applying to Google - Software Engineer",
        body="We received your application for the Senior Software Engineer role at Google.",
        sender="no-reply@google.com",
        received_date="2026-01-30",
    )

    assert result["email_class"] == "job_application_confirmation"
    assert result["confidence"] >= 0.9
    assert result["company_name"] == "Google"
    assert result["job_title"] == "Software Engineer"
    assert result["position_level"] == "Senior"
    assert result["application_stage"] == "Applied"
    assert result["processing_status"] == "completed"


def test_offer_stage_detection(monkeypatch):
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        # Return a non-offer class; offer is detected via heuristic stage logic.
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "Acme", "job_title": "Engineer", "position_level": "Mid"}
            )
        return json.dumps(
            {
                "email_class": "application_followup",
                "confidence": 0.66,
                "reasoning": "Follow-up message.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    result = lp.process_email(
        email_id="offer_1",
        subject="Offer Letter - Acme",
        body="We're pleased to offer you the position. Please review the offer letter.",
        sender="hr@acme.com",
        received_date="2026-01-30",
    )

    assert result["email_class"] == "application_followup"
    assert result["application_stage"] == "Offer"
    assert result["requires_action"] is True
    assert any("Review offer" in x for x in (result.get("action_items") or []))


def test_email_processor_persists_langgraph_fields(db_session):
    from datetime import datetime
    from app.models import Application
    from app.services.email_processor import _create_application_and_log

    state = {
        "email_id": "mid_1",
        "subject": "Thanks for applying",
        "body": "We received your application.",
        "sender": "no-reply@example.com",
        "email_class": "job_rejection",
        "confidence": 0.88,
        "classification_reasoning": "Clearly a rejection.",
        "company_name": "ExampleCo",
        "job_title": "Developer",
        "position_level": "Junior",
        "application_stage": "Rejected",
        "requires_action": False,
        "action_items": [],
        "processing_status": "completed",
    }

    _create_application_and_log(
        db_session,
        mid="mid_1",
        user_id=1,
        structured=state,
        subject=state["subject"],
        sender=state["sender"],
        body=state["body"],
        received=datetime.utcnow(),
        commit=True,
    )

    app = (
        db_session.query(Application)
        .filter(Application.gmail_message_id == "mid_1")
        .first()
    )
    assert app is not None
    assert app.category == "job_rejection"
    assert app.application_stage == "Rejected"
    assert app.status == "REJECTED"
    assert app.classification_reasoning == "Clearly a rejection."
    assert app.position_level == "Junior"
