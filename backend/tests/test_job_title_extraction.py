import pytest

from app.job_title_extraction import (
    clean_job_title,
    get_job_title_candidates,
    is_plausible_job_title,
    pick_best_job_title,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('Role: "Senior Backend Engineer" at Acme', "Senior Backend Engineer"),
        ("Position - Staff Software Engineer (Req 12345)", "Staff Software Engineer"),
        ("job title: Product Manager - Req #A-7788", "Product Manager"),
    ],
)
def test_clean_job_title_strips_wrappers(raw, expected):
    assert clean_job_title(raw) == expected


def test_candidates_from_applied_flow_body_thanks_for_applying():
    subject = "Thanks for applying to MyJunior AI!"
    body = "Thank you for applying for the Senior Full Stack Engineer role at MyJunior AI. We will review."
    cands = get_job_title_candidates(subject=subject, body=body)
    assert cands and cands[0].value == "Senior Full Stack Engineer"


def test_candidates_from_subject_interview_for():
    subject = "Interview invitation for Senior Software Engineer"
    body = "We'd like to schedule time."
    cands = get_job_title_candidates(subject=subject, body=body)
    assert cands and cands[0].value == "Senior Software Engineer"


def test_candidates_from_recruiter_outreach_label():
    subject = "Opportunity: Senior Data Engineer - Remote"
    body = "Role: Senior Data Engineer. Location: Remote."
    cands = get_job_title_candidates(subject=subject, body=body)
    assert any(c.value == "Senior Data Engineer" for c in cands)


def test_pick_best_uses_llm_value_when_plausible():
    subject = "Next steps"
    body = "We received your application for Backend Engineer."
    assert pick_best_job_title(subject=subject, body=body, llm_suggested="Backend Engineer") == "Backend Engineer"


def test_pick_best_falls_back_when_llm_is_null():
    subject = "Thank you for applying"
    body = "Thank you for applying for the Data Scientist role at ExampleCo."
    assert pick_best_job_title(subject=subject, body=body, llm_suggested=None) == "Data Scientist"


def test_plausibility_rejects_generic_words_and_urls():
    assert not is_plausible_job_title("role")
    assert not is_plausible_job_title("https://example.com/jobs/123")

