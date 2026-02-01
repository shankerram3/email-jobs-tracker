import json
import pytest


# =============================================================================
# Tests for Classification Guards
# =============================================================================

def test_has_conditional_interview_language():
    """Test that conditional interview language is correctly detected."""
    from app.langgraph_pipeline import _has_conditional_interview_language

    # Should detect conditional language
    assert _has_conditional_interview_language("If selected for an interview, we will contact you.")
    assert _has_conditional_interview_language("if we decide to move forward, a recruiter will reach out")
    assert _has_conditional_interview_language("Should you advance to the next step, we'll be in touch.")
    assert _has_conditional_interview_language("We'll reach out if there's a fit.")
    assert _has_conditional_interview_language("If you're selected for an interview")

    # Should NOT detect conditional language
    assert not _has_conditional_interview_language("We'd like to schedule an interview with you.")
    assert not _has_conditional_interview_language("Your interview is scheduled for Monday.")
    assert not _has_conditional_interview_language("Please complete the coding assessment.")


def test_has_rejection_language():
    """Test that rejection language is correctly detected."""
    from app.langgraph_pipeline import _has_rejection_language

    # Should detect rejection language
    assert _has_rejection_language("Unfortunately, we have decided not to move forward.")
    assert _has_rejection_language("We regret to inform you that the position has been filled.")
    assert _has_rejection_language("Your skills do not quite match the requirements.")
    assert _has_rejection_language("We have decided to pursue other candidates.")
    assert _has_rejection_language("After careful consideration, we will not proceed.")
    assert _has_rejection_language("Your skills do not align with what we're looking for.")

    # Should NOT detect rejection language
    assert not _has_rejection_language("Thank you for applying! We'll review your application.")
    assert not _has_rejection_language("We'd like to schedule an interview.")
    assert not _has_rejection_language("Please complete this assessment.")


def test_has_actual_interview_invitation():
    """Test that actual interview invitations are correctly detected."""
    from app.langgraph_pipeline import _has_actual_interview_invitation

    # Should detect actual interview invitations
    assert _has_actual_interview_invitation("We'd like to invite you to an interview.")
    assert _has_actual_interview_invitation("Please schedule your interview using the link below.")
    assert _has_actual_interview_invitation("Your interview is scheduled for Monday at 2pm.")
    assert _has_actual_interview_invitation("Please complete the HackerRank assessment.")
    assert _has_actual_interview_invitation("We'd like you to complete a take-home assignment.")

    # Should NOT detect actual interview invitations
    assert not _has_actual_interview_invitation("Thank you for applying.")
    assert not _has_actual_interview_invitation("We received your application.")
    assert not _has_actual_interview_invitation("If selected for an interview, we'll contact you.")


def test_conditional_language_override(monkeypatch):
    """Test that conditional language overrides interview_assessment to job_application_confirmation."""
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        # LLM incorrectly classifies as interview_assessment
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "TestCo", "job_title": "Engineer", "position_level": "Senior"}
            )
        return json.dumps(
            {
                "email_class": "interview_assessment",
                "confidence": 0.75,
                "reasoning": "Contains next steps language.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    # Email with conditional language should be overridden to job_application_confirmation
    result = lp.process_email(
        email_id="test_conditional",
        subject="Thank you for applying to TestCo",
        body="Thank you for your interest. If selected for an interview, a recruiter will reach out within two weeks.",
        sender="no-reply@testco.com",
        received_date="2026-01-30",
    )

    assert result["email_class"] == "job_application_confirmation"
    assert "[Override: conditional language" in result["classification_reasoning"]


def test_rejection_language_override(monkeypatch):
    """Test that rejection language overrides job_application_confirmation to job_rejection."""
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        # LLM incorrectly classifies as job_application_confirmation
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "RejectionCo", "job_title": "Developer", "position_level": "Mid"}
            )
        return json.dumps(
            {
                "email_class": "job_application_confirmation",
                "confidence": 0.65,
                "reasoning": "Contains thank you language.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    # Email with rejection language should be overridden to job_rejection
    result = lp.process_email(
        email_id="test_rejection",
        subject="Thank you for your interest in RejectionCo",
        body="Thank you for your interest. Unfortunately, we have decided not to move forward with your application.",
        sender="hr@rejectionco.com",
        received_date="2026-01-30",
    )

    assert result["email_class"] == "job_rejection"
    assert "[Override: rejection language detected]" in result["classification_reasoning"]


def test_actual_interview_not_overridden(monkeypatch):
    """Test that actual interview invitations are NOT overridden even with some conditional language."""
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "InterviewCo", "job_title": "Engineer", "position_level": "Senior"}
            )
        return json.dumps(
            {
                "email_class": "interview_assessment",
                "confidence": 0.85,
                "reasoning": "Contains interview scheduling.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    # Email with actual interview invitation should NOT be overridden
    result = lp.process_email(
        email_id="test_actual_interview",
        subject="Next Steps - Interview at InterviewCo",
        body="We'd like to schedule an interview with you. Please complete the HackerRank assessment first.",
        sender="recruiting@interviewco.com",
        received_date="2026-01-30",
    )

    assert result["email_class"] == "interview_assessment"
    assert "[Override" not in result["classification_reasoning"]


def test_needs_review_flag_low_confidence(monkeypatch):
    """Test that low confidence classifications are flagged for review."""
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "LowConfCo", "job_title": "Engineer", "position_level": "Mid"}
            )
        return json.dumps(
            {
                "email_class": "promotional_marketing",
                "confidence": 0.45,  # Low confidence
                "reasoning": "Uncertain classification.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    result = lp.process_email(
        email_id="test_low_confidence",
        subject="Some unclear email",
        body="This email content is ambiguous.",
        sender="unknown@example.com",
        received_date="2026-01-30",
    )

    assert result["needs_review"] is True


def test_needs_review_flag_high_confidence(monkeypatch):
    """Test that high confidence classifications are NOT flagged for review."""
    from app import langgraph_pipeline as lp

    def fake_call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
        if "Extract structured information" in prompt:
            return json.dumps(
                {"company_name": "HighConfCo", "job_title": "Engineer", "position_level": "Senior"}
            )
        return json.dumps(
            {
                "email_class": "job_application_confirmation",
                "confidence": 0.92,  # High confidence
                "reasoning": "Clear application confirmation.",
            }
        )

    monkeypatch.setattr(lp, "_call_llm", fake_call_llm)

    result = lp.process_email(
        email_id="test_high_confidence",
        subject="Thank you for applying to HighConfCo",
        body="Thank you for applying. We have received your application.",
        sender="no-reply@highconfco.com",
        received_date="2026-01-30",
    )

    assert result["needs_review"] is False


# =============================================================================
# Original Tests
# =============================================================================

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
