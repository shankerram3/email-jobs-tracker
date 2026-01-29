"""Structured email classification: one LLM call returning JSON; cache by hash; regex fallback."""
import hashlib
import json
import re
from typing import Optional, List, Tuple

from .config import settings

CATEGORIES = {
    "REJECTION",
    "INTERVIEW_REQUEST",
    "SCREENING_REQUEST",
    "ASSESSMENT",
    "RECRUITER_OUTREACH",
    "APPLICATION_RECEIVED",
    "OFFER",
    "OTHER",
}


def content_hash(subject: str, sender: str, body: str) -> str:
    """Deterministic SHA-256 hash of (subject + sender + body) for cache key."""
    content = f"{subject or ''}|{sender or ''}|{(body or '')[:5000]}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_client():
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set. Add to .env or environment.")
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _normalize_category(raw: str) -> str:
    raw = (raw or "").strip().upper()
    raw = re.sub(r"[\s\-]+", "_", raw)
    for cat in CATEGORIES:
        if cat in raw or raw == cat:
            return cat
    return "OTHER"


def _regex_salary(text: str) -> tuple[Optional[float], Optional[float]]:
    """Extract salary_min, salary_max from body using regex. Returns (min, max)."""
    text = text or ""
    min_val, max_val = None, None
    # e.g. $80,000 - $120,000; $80k-$120k; 80k-120k
    patterns = [
        r"\$?\s*([\d,]+)\s*k?\s*[-–—]\s*\$?\s*([\d,]+)\s*k?",
        r"(\d{2,3}),?\d{3}\s*[-–—]\s*(\d{2,3}),?\d{3}",
        r"salary[:\s]*\$?\s*([\d,]+)\s*[-–—]?\s*\$?\s*([\d,]+)?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                a = float(m.group(1).replace(",", ""))
                if "k" in (m.group(0) or "").lower():
                    a *= 1000
                min_val = a
                if m.lastindex >= 2 and m.group(2):
                    b = float(m.group(2).replace(",", ""))
                    if "k" in (m.group(0) or "").lower():
                        b *= 1000
                    max_val = b
                else:
                    max_val = a
                break
            except (ValueError, IndexError):
                continue
    return (min_val, max_val)


def _suggests_interview_request(body: str) -> bool:
    """True if body clearly indicates recruiter wants to schedule/conduct an interview or call."""
    text = (body or "").lower()
    phrases = [
        r"schedule\s+(?:a\s+)?(?:introductory\s+)?call",
        r"introductory\s+call",
        r"dates?\s+and\s+times?\s+(?:that\s+)?(?:work|(?:you['\u2019]?re\s+)?available)",
        r"phone\s+call\s+with\s+(?:me|us)",
        r"take\s+the\s+next\s+step",
        r"next\s+step\s+in\s+getting\s+to\s+know\s+you",
        r"get(?:ting)?\s+to\s+know\s+you\s+better",
        r"(?:would\s+like\s+to\s+)?schedule\s+.*\s+(?:call|interview)",
        r"available\s+for\s+(?:a\s+)?(?:\d+\s*[-–]\s*\d+\s+)?(?:minute\s+)?(?:phone\s+)?call",
        r"invit(e|ing)\s+you\s+for\s+(?:an?\s+)?interview",
    ]
    return any(re.search(p, text) for p in phrases)


def apply_category_overrides(result: dict, body: str) -> dict:
    """
    Apply keyword-based overrides so clear interview/screening-scheduling emails are
    INTERVIEW_REQUEST or SCREENING_REQUEST even when LLM or cache returned something else.
    """
    if not result:
        return result
    cat = result.get("category")
    if cat in ("INTERVIEW_REQUEST", "SCREENING_REQUEST"):
        return result
    if _suggests_interview_request(body or ""):
        # Prefer SCREENING_REQUEST for "intro call", "phone call", "15-30 min"; else INTERVIEW_REQUEST
        text = (body or "").lower()
        if re.search(r"(?:intro(?:ductory)?\s+call|phone\s+call|15[-–]\s*30\s+min)", text):
            result = {**result, "category": "SCREENING_REQUEST"}
        else:
            result = {**result, "category": "INTERVIEW_REQUEST"}
    return result


def _regex_job_title(subject: str, body: str) -> Optional[str]:
    """Extract job title from subject/body with regex."""
    text = f"{subject or ''} {body or ''}"[:1500]
    # "Software Engineer", "Senior Developer", "Product Manager"
    m = re.search(
        r"(?:position|role|title|hiring)\s*[:\-]?\s*([A-Z][a-zA-Z\s&]{3,50})(?:\s+at|\s*\.|\s*$|\n)",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()[:200]
    # Fallback: first "X at Company" or "X - Company"
    m = re.search(r"^([A-Za-z\s&]+)\s+(?:at|-)\s+", subject or "")
    if m:
        return m.group(1).strip()[:200]
    return None


def structured_classify_email(subject: str, body: str, sender: str) -> dict:
    """
    One structured LLM call returning:
    category, subcategory, company_name, job_title, salary_min, salary_max, location, confidence.
    On LLM failure, use regex fallback for salary and job_title; category defaults to OTHER.
    """
    body_sample = (body or "")[:2000]
    prompt = f"""Classify this job application email and extract structured data.

Category definitions (pick the best match):
- INTERVIEW_REQUEST: Recruiter/company wants to schedule or conduct a full interview (e.g. onsite, panel, technical round).
- SCREENING_REQUEST: Recruiter/company wants to schedule a screening call (phone screen, intro call, "15-30 min call", "get to know you", "dates and times that work"). Use for initial recruiter calls before a full interview.
- APPLICATION_RECEIVED: Automated or brief confirmation that your application was received (no interview scheduling).
- RECRUITER_OUTREACH: Unsolicited outreach about a role (you didn't apply yet).
- ASSESSMENT: Coding test, take-home, or assessment invite.
- REJECTION: You are not moving forward / not selected.
- OFFER: Job offer or compensation discussion.
- OTHER: None of the above.

Return a JSON object with exactly these keys (use null for unknown):
- category: one of REJECTION, INTERVIEW_REQUEST, SCREENING_REQUEST, ASSESSMENT, RECRUITER_OUTREACH, APPLICATION_RECEIVED, OFFER, OTHER
- subcategory: optional string (e.g. "phone_screen", "onsite")
- company_name: string company name or "Unknown"
- job_title: string job title or null
- salary_min: number or null (annual USD)
- salary_max: number or null (annual USD)
- location: string or null
- confidence: number 0.0 to 1.0

Email:
Subject: {subject}
From: {sender}
Body: {body_sample}

Return ONLY valid JSON, no other text."""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (response.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
        data = json.loads(text)
    except Exception:
        data = {}

    category = _normalize_category(str(data.get("category") or "OTHER"))
    subcategory = (data.get("subcategory") or "").strip() or None
    company_name = (data.get("company_name") or "Unknown").strip()[:255]
    job_title = (data.get("job_title") or "").strip() or None
    if job_title:
        job_title = job_title[:255]
    salary_min = data.get("salary_min")
    if salary_min is not None and not isinstance(salary_min, (int, float)):
        salary_min = None
    salary_max = data.get("salary_max")
    if salary_max is not None and not isinstance(salary_max, (int, float)):
        salary_max = None
    location = (data.get("location") or "").strip() or None
    if location:
        location = location[:255]
    confidence = data.get("confidence")
    if confidence is not None and isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = None

    # Regex fallbacks if LLM didn't return
    if salary_min is None and salary_max is None:
        salary_min, salary_max = _regex_salary(body or "")
    if not job_title:
        job_title = _regex_job_title(subject or "", body or "")

    result = {
        "category": category,
        "subcategory": subcategory,
        "company_name": company_name or "Unknown",
        "job_title": job_title,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "location": location,
        "confidence": confidence,
    }
    return apply_category_overrides(result, body)


def classify_email_llm_only(subject: str, body: str, sender: str) -> dict:
    """
    LLM-only classification (no DB, no cache). Safe to call from worker threads.
    Returns same structure as structured_classify_email.
    """
    return structured_classify_email(subject, body, sender)


def _parse_single_result(data: dict, subject: str, body: str, sender: str) -> dict:
    """Build one classification dict from raw LLM data + regex fallbacks."""
    category = _normalize_category(str(data.get("category") or "OTHER"))
    subcategory = (data.get("subcategory") or "").strip() or None
    company_name = (data.get("company_name") or "Unknown").strip()[:255]
    job_title = (data.get("job_title") or "").strip() or None
    if job_title:
        job_title = job_title[:255]
    salary_min = data.get("salary_min")
    if salary_min is not None and not isinstance(salary_min, (int, float)):
        salary_min = None
    salary_max = data.get("salary_max")
    if salary_max is not None and not isinstance(salary_max, (int, float)):
        salary_max = None
    location = (data.get("location") or "").strip() or None
    if location:
        location = location[:255]
    confidence = data.get("confidence")
    if confidence is not None and isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = None
    if salary_min is None and salary_max is None:
        salary_min, salary_max = _regex_salary(body or "")
    if not job_title:
        job_title = _regex_job_title(subject or "", body or "")
    return {
        "category": category,
        "subcategory": subcategory,
        "company_name": company_name or "Unknown",
        "job_title": job_title,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "location": location,
        "confidence": confidence,
    }


def structured_classify_emails_batch(
    emails: List[Tuple[str, str, str]],
) -> List[dict]:
    """
    Classify multiple emails in one LLM call. emails = [(subject, body, sender), ...].
    Returns list of classification dicts (same schema as structured_classify_email).
    On parse failure or length mismatch returns empty list so caller can fall back to per-email.
    """
    if not emails:
        return []
    parts = []
    for i, (subject, body, sender) in enumerate(emails):
        body_sample = (body or "")[:1500]
        parts.append(
            f"--- Email {i + 1} ---\nSubject: {subject}\nFrom: {sender}\nBody: {body_sample}"
        )
    combined = "\n\n".join(parts)
    prompt = f"""Classify each of the following job application emails and extract structured data.

Category definitions (pick the best match for each email):
- INTERVIEW_REQUEST: Recruiter/company wants to schedule or conduct a full interview (onsite, panel, technical round).
- SCREENING_REQUEST: Recruiter/company wants to schedule a screening call (phone screen, intro call, "15-30 min call", "get to know you", "dates and times that work"). Use for initial recruiter calls before a full interview.
- APPLICATION_RECEIVED: Automated or brief confirmation that your application was received (no interview scheduling).
- RECRUITER_OUTREACH: Unsolicited outreach about a role (you didn't apply yet).
- ASSESSMENT: Coding test, take-home, or assessment invite.
- REJECTION: You are not moving forward / not selected.
- OFFER: Job offer or compensation discussion.
- OTHER: None of the above.

Return a JSON array of objects. Each object must have exactly these keys (use null for unknown):
- category: one of REJECTION, INTERVIEW_REQUEST, SCREENING_REQUEST, ASSESSMENT, RECRUITER_OUTREACH, APPLICATION_RECEIVED, OFFER, OTHER
- subcategory: optional string (e.g. "phone_screen", "onsite")
- company_name: string company name or "Unknown"
- job_title: string job title or null
- salary_min: number or null (annual USD)
- salary_max: number or null (annual USD)
- location: string or null
- confidence: number 0.0 to 1.0

Emails:

{combined}

Return ONLY a valid JSON array of {len(emails)} objects, no other text."""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=min(400 * len(emails) + 200, 4096),
            messages=[{"role": "user", "content": prompt}],
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
        arr = json.loads(text)
        if not isinstance(arr, list) or len(arr) != len(emails):
            return []
        results = []
        for i, data in enumerate(arr):
            if not isinstance(data, dict):
                r = _parse_single_result({}, *emails[i])
            else:
                r = _parse_single_result(data, *emails[i])
            _, body, _ = emails[i]
            results.append(apply_category_overrides(r, body))
        return results
    except Exception:
        return []


def normalize_company_name(name: str) -> str:
    """Strip suffixes like Inc/LLC/Corp and trim."""
    if not name or name == "Unknown":
        return name
    name = name.strip()
    for suffix in re.split(r"[\s,]+", "Inc LLC Corp Ltd Co. Company L.L.C. L.L.C"):
        pattern = re.compile(re.escape(suffix) + r"\.?\s*$", re.I)
        name = pattern.sub("", name).strip()
    return name[:255] if name else "Unknown"


def classify_email(subject: str, body: str, sender: str) -> str:
    """Legacy: return only category. Use structured_classify_email for full payload."""
    result = structured_classify_email(subject, body, sender)
    return result["category"]


def extract_company_name(subject: str, body: str, sender: str) -> str:
    """Legacy: return only company. Use structured_classify_email for full payload."""
    result = structured_classify_email(subject, body, sender)
    return normalize_company_name(result["company_name"])
