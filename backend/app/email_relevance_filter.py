"""
Email relevance filter - filters out non-job-related emails using LLM + rules.

This module provides a two-stage filtering approach:
1. Fast rule-based filtering for obvious non-job emails
2. LLM-based filtering for ambiguous cases
"""

import re
from typing import Optional

# Lazy import to avoid circular dependencies and missing module issues
def _get_settings():
    from .config import settings
    return settings


# Known non-job sender domains - expand as needed
NON_JOB_SENDER_DOMAINS = {
    # Payment/billing
    "billing", "payments", "invoice", "receipt",
    # Newsletters/marketing
    "newsletter", "marketing", "promo", "campaigns", "news",
    # Social media
    "facebookmail.com", "twitter.com", "linkedin.com", "instagram.com",
    # E-commerce
    "amazon.com", "ebay.com", "shopify.com",
    # Subscriptions/services (non-recruiting)
    "openai.com", "chatgpt.com", "notion.so", "slack.com", "zoom.us",
    "spotify.com", "netflix.com", "apple.com", "google.com",
    "dropbox.com", "adobe.com", "microsoft.com",
    # Banks/finance (non-job)
    "chase.com", "bankofamerica.com", "wellsfargo.com", "paypal.com",
    "venmo.com", "capitalone.com",
}

# Sender patterns that indicate non-job emails
NON_JOB_SENDER_PATTERNS = [
    r"no[-_]?reply@",
    r"noreply@",
    r"do[-_]?not[-_]?reply@",
    r"billing@",
    r"payments?@",
    r"support@(?!.*(?:greenhouse|lever|workday|icims|taleo|jobvite))",  # support@ unless from ATS
    r"newsletter@",
    r"notifications?@(?!.*(?:greenhouse|lever|workday|icims|taleo|jobvite))",
    r"marketing@",
    r"promo(?:tions?)?@",
    r"info@(?!.*(?:greenhouse|lever|workday|icims|taleo|jobvite))",  # generic info@ unless from ATS
    r"receipt@",
    r"invoice@",
    r"order@",
    r"shipping@",
    r"delivery@",
]

# Subject patterns that strongly indicate non-job emails
NON_JOB_SUBJECT_PATTERNS = [
    # Billing/payments
    r"(?:update|confirm).*(?:payment|billing|subscription)",
    r"(?:payment|subscription|billing)\s+(?:failed|declined|updated|confirmed)",
    r"your\s+(?:receipt|invoice|order|purchase)",
    r"renew(?:al)?\s+(?:reminder|notice)",
    r"(?:credit\s+card|payment\s+method)\s+(?:expir|update|declined)",
    # Account notifications (non-job)
    r"password\s+(?:reset|changed|updated)",
    r"(?:verify|confirm)\s+your\s+(?:email|account)",
    r"(?:security|login)\s+(?:alert|notification)",
    r"two[-\s]?factor\s+authentication",
    r"sign[-\s]?in\s+(?:alert|attempt|notification)",
    # Shipping/orders
    r"(?:order|shipment|package)\s+(?:shipped|delivered|confirmed|tracking)",
    r"delivery\s+(?:update|confirmation|notification)",
    # Marketing/promotions
    r"(?:exclusive|special|limited\s+time)\s+offer",
    r"(?:save|discount|sale|deal|promo)",
    r"(?:black\s+friday|cyber\s+monday|holiday\s+sale)",
    # Social media
    r"(?:new\s+)?(?:follower|like|comment|mention|message)\s+(?:on|from)",
    r"someone\s+(?:liked|commented|mentioned|followed)",
    # News/newsletters
    r"(?:weekly|daily|monthly)\s+(?:digest|newsletter|roundup|update)",
    r"top\s+(?:stories|news|articles)",
]

# Keywords that strongly suggest job-related content
JOB_RELATED_KEYWORDS = [
    r"application\s+(?:received|status|update)",
    r"thank\s+you\s+for\s+applying",
    r"interview\s+(?:invitation|request|schedule)",
    r"(?:phone|video|onsite|technical)\s+(?:screen|interview)",
    r"recruiter",
    r"hiring\s+(?:manager|team)",
    r"job\s+(?:offer|opportunity|opening|posting)",
    r"position\s+(?:at|with|for)",
    r"(?:coding|technical|assessment)\s+(?:challenge|test)",
    r"(?:hackerrank|codesignal|codility|leetcode)",
    r"(?:offer|compensation)\s+(?:letter|package|details)",
    r"background\s+check",
    r"start\s+date",
    r"onboarding",
]

# Known ATS (Applicant Tracking System) domains - these are always job-related
ATS_DOMAINS = {
    "greenhouse.io", "lever.co", "workday.com", "icims.com",
    "taleo.net", "jobvite.com", "smartrecruiters.com", "breezy.hr",
    "ashbyhq.com", "bamboohr.com", "successfactors.com", "myworkday.com",
    "myworkdayjobs.com", "ultipro.com", "adp.com", "ceridian.com",
}


def _normalize_text(text: str) -> str:
    """Normalize text for pattern matching."""
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _extract_domain(email: str) -> Optional[str]:
    """Extract domain from email address."""
    match = re.search(r"@([\w.-]+)", email or "")
    return match.group(1).lower() if match else None


def _is_from_ats(sender: str) -> bool:
    """Check if sender is from a known ATS."""
    domain = _extract_domain(sender)
    if not domain:
        return False
    return any(ats in domain for ats in ATS_DOMAINS)


def rule_based_relevance_check(subject: str, body: str, sender: str) -> Optional[bool]:
    """
    Fast rule-based check for email relevance.

    Returns:
        True: Definitely job-related
        False: Definitely NOT job-related
        None: Uncertain, needs LLM check
    """
    subject_norm = _normalize_text(subject)
    body_norm = _normalize_text(body[:2000])
    sender_norm = _normalize_text(sender)
    combined = f"{subject_norm} {body_norm}"

    # Check if from ATS - always relevant
    if _is_from_ats(sender):
        return True

    # Check for strong job-related keywords first
    for pattern in JOB_RELATED_KEYWORDS:
        if re.search(pattern, combined, re.I):
            return True

    # Check sender domain against known non-job domains
    domain = _extract_domain(sender)
    if domain:
        for non_job_domain in NON_JOB_SENDER_DOMAINS:
            if non_job_domain in domain:
                # Unless it contains job keywords
                if not any(re.search(p, combined, re.I) for p in JOB_RELATED_KEYWORDS):
                    return False

    # Check sender patterns
    for pattern in NON_JOB_SENDER_PATTERNS:
        if re.search(pattern, sender_norm, re.I):
            # Unless it contains job keywords
            if not any(re.search(p, combined, re.I) for p in JOB_RELATED_KEYWORDS):
                return False

    # Check subject patterns
    for pattern in NON_JOB_SUBJECT_PATTERNS:
        if re.search(pattern, subject_norm, re.I):
            return False

    # Uncertain - needs LLM check
    return None


def llm_relevance_check(subject: str, body: str, sender: str) -> tuple[bool, float, str]:
    """
    LLM-based relevance check for ambiguous emails.

    Returns:
        (is_relevant, confidence, reason)
    """
    try:
        from openai import OpenAI
        settings = _get_settings()
        client = OpenAI(api_key=settings.openai_api_key)

        body_sample = (body or "")[:1500]

        prompt = f"""Determine if this email is related to a JOB APPLICATION or RECRUITING process.

Job-related emails include:
- Application confirmations/status updates
- Interview invitations or scheduling
- Recruiter outreach about job opportunities
- Assessment/coding challenge invitations
- Rejection notices
- Job offers
- Background check or onboarding emails

NOT job-related (return false):
- Payment/billing notifications
- Subscription renewals
- Marketing/promotional emails
- Social media notifications
- News/newsletters
- Account security alerts
- Order/shipping confirmations
- General product updates (like "ChatGPT Plus features")

Email:
From: {sender}
Subject: {subject}
Body: {body_sample}

Return JSON with:
- "is_job_related": boolean (true if job/recruiting related)
- "confidence": number 0.0-1.0
- "reason": brief explanation (max 50 words)

Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use cheaper model for filtering
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are an email classifier. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )

        import json
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
        data = json.loads(text)

        is_relevant = bool(data.get("is_job_related", True))
        confidence = float(data.get("confidence", 0.5))
        reason = str(data.get("reason", ""))[:200]

        return (is_relevant, confidence, reason)

    except Exception as e:
        # On error, default to relevant (don't filter out potentially important emails)
        return (True, 0.5, f"LLM check failed: {str(e)[:50]}")


def is_job_related_email(subject: str, body: str, sender: str) -> tuple[bool, float, str]:
    """
    Main entry point: determine if email is job-related.

    Uses fast rules first, falls back to LLM for ambiguous cases.

    Returns:
        (is_relevant, confidence, reason)
    """
    # Try rule-based check first (fast)
    rule_result = rule_based_relevance_check(subject, body, sender)

    if rule_result is True:
        return (True, 0.95, "Matches job-related patterns")
    elif rule_result is False:
        return (False, 0.90, "Matches non-job patterns (billing/marketing/etc)")

    # Ambiguous - use LLM
    return llm_relevance_check(subject, body, sender)


def filter_job_emails(emails: list[dict]) -> list[dict]:
    """
    Filter a list of emails, keeping only job-related ones.

    Each email dict should have 'subject', 'body', 'sender' keys.
    Adds 'relevance_confidence' and 'relevance_reason' to each returned email.
    """
    job_emails = []

    for email in emails:
        subject = email.get("subject", "")
        body = email.get("body", "")
        sender = email.get("sender", "") or email.get("from", "")

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)

        if is_relevant:
            email["relevance_confidence"] = confidence
            email["relevance_reason"] = reason
            job_emails.append(email)

    return job_emails
