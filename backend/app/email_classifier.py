"""AI-powered email classification using OpenAI."""
import re

from .config import settings

# Allowed categories for validation
CATEGORIES = {
    "REJECTION",
    "INTERVIEW_REQUEST",
    "ASSESSMENT",
    "RECRUITER_OUTREACH",
    "APPLICATION_RECEIVED",
    "OFFER",
    "OTHER",
}


def _get_client():
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set. Add to .env or environment.")
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _normalize_category(raw: str) -> str:
    """Map model output to one of CATEGORIES."""
    raw = (raw or "").strip().upper()
    raw = re.sub(r"[\s\-]+", "_", raw)
    for cat in CATEGORIES:
        if cat in raw or raw == cat:
            return cat
    return "OTHER"


def classify_email(subject: str, body: str, sender: str) -> str:
    """
    Classify job application email into one of:
    REJECTION, INTERVIEW_REQUEST, ASSESSMENT, RECRUITER_OUTREACH,
    APPLICATION_RECEIVED, OFFER, OTHER.
    """
    body_sample = (body or "")[:1000]
    prompt = f"""Classify this job application email into ONE category.

Categories:
- REJECTION: Email rejecting the application
- INTERVIEW_REQUEST: Requesting to schedule an interview
- ASSESSMENT: Technical assessment/coding challenge invitation
- RECRUITER_OUTREACH: Direct recruiter reaching out about opportunity
- APPLICATION_RECEIVED: Confirmation that application was received
- OFFER: Job offer or offer-related
- OTHER: Doesn't fit above categories

Email details:
Subject: {subject}
From: {sender}
Body: {body_sample}

Return ONLY the category name, nothing else."""

    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    text = (response.choices[0].message.content or "").strip()
    return _normalize_category(text)


def extract_company_name(subject: str, body: str, sender: str) -> str:
    """Extract company name from email. Returns 'Unknown' if unclear."""
    body_sample = (body or "")[:500]
    prompt = f"""Extract the company name from this job application email.

Subject: {subject}
From: {sender}
Body: {body_sample}

Return ONLY the company name, nothing else. If unclear, return "Unknown"."""

    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=50,
        messages=[{"role": "user", "content": prompt}],
    )
    name = (response.choices[0].message.content or "").strip() or "Unknown"
    return name[:255]
