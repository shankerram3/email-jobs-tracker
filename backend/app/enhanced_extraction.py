"""
Enhanced extraction module - uses LLM for better company/job title/body extraction.

This module provides dedicated extraction functions that can be used as a
post-processing step after initial classification, or as part of a two-pass
LLM pipeline.
"""

import re
import json
from typing import Optional
from .config import settings


def _get_client():
    """Get OpenAI client."""
    from openai import OpenAI
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=api_key)


def _clean_json_response(text: str) -> str:
    """Clean markdown code blocks from JSON response."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
    return text


def extract_company_name(subject: str, body: str, sender: str) -> tuple[str, float]:
    """
    Extract company name using dedicated LLM call.

    Returns:
        (company_name, confidence)
    """
    try:
        client = _get_client()
        body_sample = (body or "")[:2000]

        prompt = f"""Extract the COMPANY NAME from this job-related email.

Rules:
1. Look for the company that is HIRING (not recruiters/staffing agencies unless that's all there is)
2. Check the sender domain for clues (e.g., @google.com → Google)
3. Look for "at [Company]", "[Company] is hiring", "team at [Company]"
4. If multiple companies mentioned, prefer the one doing the hiring
5. Remove suffixes like Inc, LLC, Corp, Ltd from the name
6. If truly unknown, return "Unknown"

Email:
From: {sender}
Subject: {subject}
Body: {body_sample}

Return JSON with:
- "company_name": string (the company name, or "Unknown")
- "confidence": number 0.0-1.0
- "source": where you found it ("sender_domain", "body", "subject", "unknown")

Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=100,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Extract company name. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )

        data = json.loads(_clean_json_response(response.choices[0].message.content))
        company = (data.get("company_name") or "Unknown").strip()
        confidence = float(data.get("confidence", 0.5))

        # Normalize company name
        company = _normalize_company(company)

        return (company, confidence)

    except Exception:
        # Fallback to sender domain extraction
        return (_extract_company_from_sender(sender), 0.3)


def _normalize_company(name: str) -> str:
    """Remove common suffixes from company name."""
    if not name or name == "Unknown":
        return name
    name = name.strip()
    suffixes = ["Inc", "Inc.", "LLC", "L.L.C.", "Corp", "Corp.", "Corporation",
                "Ltd", "Ltd.", "Limited", "Co", "Co.", "Company", "PLC", "GmbH"]
    for suffix in suffixes:
        pattern = re.compile(r",?\s*" + re.escape(suffix) + r"\.?\s*$", re.I)
        name = pattern.sub("", name).strip()
    return name if name else "Unknown"


def _extract_company_from_sender(sender: str) -> str:
    """Extract company name from sender email domain."""
    match = re.search(r"@([\w.-]+)", sender or "")
    if not match:
        return "Unknown"

    domain = match.group(1).lower()

    # Skip generic domains
    generic = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
               "icloud.com", "mail.com", "protonmail.com", "aol.com"}
    if domain in generic:
        return "Unknown"

    # Skip common ATS domains (the company name is in the subdomain/email body)
    ats_domains = {"greenhouse.io", "lever.co", "myworkdayjobs.com"}
    if any(ats in domain for ats in ats_domains):
        return "Unknown"

    # Extract company from domain (remove TLD)
    parts = domain.split(".")
    if len(parts) >= 2:
        company = parts[-2]  # e.g., "google" from "google.com"
        return company.title()

    return "Unknown"


def extract_job_title(subject: str, body: str, sender: str) -> tuple[Optional[str], float]:
    """
    Extract job title using dedicated LLM call.

    Returns:
        (job_title, confidence) - job_title may be None
    """
    try:
        client = _get_client()
        body_sample = (body or "")[:2000]

        prompt = f"""Extract the JOB TITLE from this job-related email.

Rules:
1. Look for specific role names like "Software Engineer", "Product Manager", etc.
2. Common patterns: "application for [Title]", "position: [Title]", "[Title] role at"
3. Include level if present (Senior, Staff, Principal, Junior, etc.)
4. Include specialization if present (Backend, Frontend, Full Stack, ML, etc.)
5. Do NOT include company name in the title
6. Do NOT include location in the title
7. If no clear job title found, return null

Examples of good job titles:
- "Senior Software Engineer"
- "Staff Product Manager"
- "ML Engineer, NLP"
- "Frontend Developer"
- "Data Scientist II"

NOT job titles (return null for these):
- "Your Application"
- "Interview Invitation"
- "Next Steps"
- Just a company name

Email:
From: {sender}
Subject: {subject}
Body: {body_sample}

Return JSON with:
- "job_title": string or null
- "confidence": number 0.0-1.0

Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=100,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Extract job title. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )

        data = json.loads(_clean_json_response(response.choices[0].message.content))
        title = data.get("job_title")
        if title:
            title = _clean_job_title(title)
        confidence = float(data.get("confidence", 0.5))

        return (title, confidence)

    except Exception:
        return (None, 0.0)


def _clean_job_title(title: str) -> Optional[str]:
    """Clean and validate job title."""
    if not title:
        return None

    title = title.strip()

    # Remove common non-title phrases
    invalid_titles = [
        "your application", "application received", "interview invitation",
        "next steps", "thank you", "unknown", "n/a", "none"
    ]
    if title.lower() in invalid_titles:
        return None

    # Remove "at Company" suffix
    title = re.sub(r"\s+at\s+[A-Z][\w\s&.,'-]*$", "", title, flags=re.I)

    # Remove trailing punctuation
    title = title.rstrip(" .,:;|/\\-")

    # Validate length
    if len(title) < 3 or len(title) > 100:
        return None

    return title if title else None


def summarize_email_body(subject: str, body: str, sender: str) -> tuple[str, list[str]]:
    """
    Summarize email body into clean, structured content.

    Returns:
        (summary, key_points) - summary is a brief description, key_points are action items/important info
    """
    try:
        client = _get_client()
        body_sample = (body or "")[:3000]

        prompt = f"""Summarize this job-related email into clean, useful content.

Remove:
- Email signatures
- Legal disclaimers
- Unsubscribe links
- Marketing boilerplate
- Social media links

Keep:
- The main message/action required
- Important dates/deadlines
- Contact information (if relevant to action)
- Next steps

Email:
From: {sender}
Subject: {subject}
Body: {body_sample}

Return JSON with:
- "summary": 1-2 sentence summary of the email's purpose (max 200 chars)
- "key_points": array of 1-3 important points/action items (each max 100 chars)
- "clean_body": the essential content without boilerplate (max 500 chars)

Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            max_tokens=400,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Summarize job email. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )

        data = json.loads(_clean_json_response(response.choices[0].message.content))
        summary = (data.get("summary") or "")[:500]
        key_points = data.get("key_points", [])
        if not isinstance(key_points, list):
            key_points = []
        key_points = [str(p)[:200] for p in key_points[:5]]

        return (summary, key_points)

    except Exception:
        # Return truncated original body on error
        return (body[:200] + "..." if len(body) > 200 else body, [])


def enhanced_extract_all(subject: str, body: str, sender: str) -> dict:
    """
    Perform enhanced extraction of all fields in one LLM call.

    This is more efficient than calling each function separately.

    Returns dict with:
        - company_name
        - company_confidence
        - job_title
        - job_title_confidence
        - summary
        - key_points
        - clean_body
    """
    try:
        client = _get_client()
        body_sample = (body or "")[:2500]

        prompt = f"""Analyze this job-related email and extract structured information.

Extract:
1. COMPANY NAME: The company that is hiring (not staffing agencies). Check sender domain, body text.
2. JOB TITLE: The specific role (e.g., "Senior Software Engineer"). Not "Your Application" or generic phrases.
3. SUMMARY: 1-2 sentence summary of email purpose.
4. KEY POINTS: Important action items or dates.
5. CLEAN BODY: Essential content without signatures/disclaimers/marketing.

Email:
From: {sender}
Subject: {subject}
Body: {body_sample}

Return JSON with:
{{
  "company_name": string or "Unknown",
  "company_confidence": number 0.0-1.0,
  "job_title": string or null,
  "job_title_confidence": number 0.0-1.0,
  "summary": string (max 200 chars),
  "key_points": array of strings (max 3 items),
  "clean_body": string (essential content, max 500 chars)
}}

Return ONLY valid JSON."""

        response = client.chat.completions.create(
            model=settings.openai_model,  # Use main model for comprehensive extraction
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Extract job email info. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )

        data = json.loads(_clean_json_response(response.choices[0].message.content))

        company = _normalize_company(data.get("company_name", "Unknown"))
        job_title = _clean_job_title(data.get("job_title"))

        return {
            "company_name": company if company else "Unknown",
            "company_confidence": float(data.get("company_confidence", 0.5)),
            "job_title": job_title,
            "job_title_confidence": float(data.get("job_title_confidence", 0.5)) if job_title else 0.0,
            "summary": (data.get("summary") or "")[:500],
            "key_points": [str(p)[:200] for p in (data.get("key_points") or [])[:5]],
            "clean_body": (data.get("clean_body") or body_sample[:500])[:1000],
        }

    except Exception as e:
        # Fallback with basic extraction
        return {
            "company_name": _extract_company_from_sender(sender),
            "company_confidence": 0.3,
            "job_title": None,
            "job_title_confidence": 0.0,
            "summary": subject or "",
            "key_points": [],
            "clean_body": body[:500] if body else "",
        }


def refine_classification_result(
    existing_result: dict,
    subject: str,
    body: str,
    sender: str,
    force_extract: bool = False
) -> dict:
    """
    Refine an existing classification result with better extraction.

    Use this to post-process results from the main classifier when:
    - company_name is "Unknown"
    - job_title is None
    - You want cleaner body content

    Args:
        existing_result: Dict from structured_classify_email
        subject, body, sender: Email content
        force_extract: If True, always re-extract even if fields are present

    Returns:
        Updated result dict with improved extractions
    """
    result = existing_result.copy()

    needs_extraction = (
        force_extract or
        result.get("company_name") in (None, "Unknown", "") or
        result.get("job_title") in (None, "")
    )

    if needs_extraction:
        extracted = enhanced_extract_all(subject, body, sender)

        # Update company if we got a better one
        if result.get("company_name") in (None, "Unknown", ""):
            result["company_name"] = extracted["company_name"]
            result["company_confidence"] = extracted["company_confidence"]

        # Update job title if we got one
        if result.get("job_title") in (None, ""):
            result["job_title"] = extracted["job_title"]
            result["job_title_confidence"] = extracted["job_title_confidence"]

        # Add summary info
        result["summary"] = extracted.get("summary", "")
        result["key_points"] = extracted.get("key_points", [])
        result["clean_body"] = extracted.get("clean_body", "")

    return result
