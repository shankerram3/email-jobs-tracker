"""Structured email classification: one LLM call returning JSON; cache by hash; regex fallback."""
import hashlib
import json
import re
from typing import Optional, List, Tuple, Iterable

from .config import settings
from .job_title_extraction import get_job_title_candidates, pick_best_job_title
from .email_relevance_filter import is_job_related_email, rule_based_relevance_check
from .enhanced_extraction import refine_classification_result, enhanced_extract_all

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


def _normalize_text(*parts: str) -> str:
    text = " ".join(p or "" for p in parts)
    text = re.sub(r"\s+", " ", text.lower())
    return text.strip()


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _has_conditional_interview_language(text: str) -> bool:
    conditional_phrases = [
        r"if\s+(?:you(?:'|’)?re|we(?:'|’)?re)\s+selected\s+for\s+an?\s+interview",
        r"if\s+selected\s+for\s+an?\s+interview",
        r"if\s+we\s+decide\s+to\s+move\s+forward",
        r"if\s+we\s+move\s+forward",
        r"should\s+you\s+advance\s+to\s+the\s+next\s+step",
        r"if\s+chosen\s+to\s+move\s+forward",
    ]
    return _matches_any(text, conditional_phrases)


def _rule_based_category(subject: str, body: str, sender: str) -> Optional[str]:
    """Return a strong rule-based category when we are confident; otherwise None."""
    text = _normalize_text(subject, body, sender)

    offer_phrases = [
        r"we(?:'|’)?re\s+pleased\s+to\s+offer",
        r"we(?:'|’)?d\s+like\s+to\s+extend\s+an?\s+offer",
        r"offer\s+letter",
        r"congratulations\s+on\s+your\s+offer",
        r"compensation\s+package",
    ]
    if _matches_any(text, offer_phrases):
        return "OFFER"

    rejection_phrases = [
        r"unfortunately",
        r"regret\s+to\s+inform",
        r"we(?:'|’)?re\s+sorry\s+to\s+inform",
        r"not\s+moving\s+forward",
        r"will\s+not\s+be\s+moving\s+forward",
        r"decided\s+to\s+move\s+forward\s+with\s+other\s+candidates",
        r"not\s+selected",
        r"position\s+has\s+been\s+filled",
        r"we\s+will\s+not\s+proceed",
    ]
    if _matches_any(text, rejection_phrases):
        return "REJECTION"

    assessment_phrases = [
        r"coding\s+challenge",
        r"take[-\s]?home\s+assignment",
        r"assessment",
        r"online\s+assessment",
        r"hackerrank",
        r"codesignal",
        r"codility",
        r"technical\s+assessment",
        r"skill\s+assessment",
    ]
    if _matches_any(text, assessment_phrases):
        return "ASSESSMENT"

    interview_phrases = [
        r"invit(?:e|ing)\s+you\s+for\s+an?\s+interview",
        r"schedule\s+an?\s+interview",
        r"interview\s+with\s+our\s+team",
        r"next\s+step.*interview",
        r"interview\s+process",
        r"onsite\s+interview",
        r"panel\s+interview",
        r"technical\s+interview",
    ]
    screening_phrases = [
        r"intro(?:ductory)?\s+call",
        r"phone\s+screen",
        r"recruiter\s+screen",
        r"screening\s+call",
        r"15[-–]\s*30\s+min(?:ute)?\s+call",
        r"schedule\s+(?:a\s+)?call",
        r"available\s+for\s+(?:a\s+)?call",
        r"dates?\s+and\s+times?\s+(?:that\s+)?(?:work|(?:you['\u2019]?re\s+)?available)",
    ]

    if _matches_any(text, screening_phrases):
        return "SCREENING_REQUEST"
    if _matches_any(text, interview_phrases):
        return "INTERVIEW_REQUEST"

    application_received_phrases = [
        r"thank\s+you\s+for\s+applying",
        r"thanks?\s+for\s+applying",
        r"we\s+received\s+your\s+application",
        r"application\s+received",
        r"your\s+application\s+has\s+been\s+received",
        r"we\s+appreciate\s+your\s+interest",
        r"thanks?\s+for\s+your\s+interest",
        r"we(?:'|’)?ll\s+review\s+your\s+application",
        r"reviewing\s+your\s+application",
    ]
    if _matches_any(text, application_received_phrases) or _has_conditional_interview_language(text):
        return "APPLICATION_RECEIVED"

    recruiter_outreach_phrases = [
        r"came\s+across\s+your\s+profile",
        r"found\s+your\s+profile",
        r"noticed\s+your\s+profile",
        r"reaching\s+out\s+about\s+an?\s+opportunity",
        r"would\s+you\s+be\s+interested\s+in",
        r"opportunity\s+for\s+you",
    ]
    if _matches_any(text, recruiter_outreach_phrases):
        return "RECRUITER_OUTREACH"

    return None


def apply_category_overrides(result: dict, subject: str, body: str, sender: str) -> dict:
    """
    Apply keyword-based overrides so clear outcomes (offer, rejection, assessment,
    screening/interview scheduling, or application received) supersede LLM output.
    """
    if not result:
        return result

    rule_category = _rule_based_category(subject, body, sender)
    if rule_category:
        return {**result, "category": rule_category}

    # Guard against LLM over-weighting conditional interview language
    if result.get("category") in ("INTERVIEW_REQUEST", "SCREENING_REQUEST"):
        text = _normalize_text(subject, body)
        if _has_conditional_interview_language(text):
            return {**result, "category": "APPLICATION_RECEIVED"}
    return result


def _regex_job_title(subject: str, body: str) -> Optional[str]:
    """Extract job title from subject/body with regex."""
    # Prefer shared deterministic extractor to keep behavior consistent with LangGraph.
    body_sample = (body or "")[:2000]
    cands = get_job_title_candidates(subject=subject or "", body=body_sample)
    if cands:
        return cands[0].value[:200]

    # Last-resort: keep legacy regex behavior as a safety net.
    text = f"{subject or ''} {body or ''}"[:1500]
    m = re.search(
        r"(?:position|role|title|hiring)\s*[:\-]?\s*([A-Z][a-zA-Z\s&]{3,50})(?:\s+at|\s*\.|\s*$|\n)",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()[:200]
    m = re.search(r"^([A-Za-z\s&]+)\s+(?:at|-)\s+", subject or "")
    if m:
        return m.group(1).strip()[:200]
    return pick_best_job_title(subject=subject or "", body=body_sample, llm_suggested=None)


def structured_classify_email(subject: str, body: str, sender: str) -> dict:
    """
    One structured LLM call returning:
    category, subcategory, company_name, job_title, salary_min, salary_max, location, confidence.
    On LLM failure, use regex fallback for salary and job_title; category defaults to OTHER.
    """
    body_sample = (body or "")[:2000]
    prompt = f"""You are an email triage model for job-application workflows.
Follow the category definitions exactly and return strict JSON only.
Important: phrases like "if selected for an interview" or "if we move forward"
mean APPLICATION_RECEIVED, not INTERVIEW_REQUEST or SCREENING_REQUEST.

Classify this job application email and extract structured data.

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

Examples:

Subject: Thank you for applying to DigitalOcean!
Body: Thank you for your interest... If selected for an interview, a recruiter will reach out within two weeks.
JSON: {{"category":"APPLICATION_RECEIVED","subcategory":null,"company_name":"DigitalOcean","job_title":"Senior Software Engineer","salary_min":null,"salary_max":null,"location":null,"confidence":0.68}}

Subject: Interview invitation for Senior Software Engineer
Body: We'd like to schedule a 30 minute phone screen. Please share times that work.
JSON: {{"category":"SCREENING_REQUEST","subcategory":"phone_screen","company_name":"Unknown","job_title":"Senior Software Engineer","salary_min":null,"salary_max":null,"location":null,"confidence":0.76}}

Subject: Next steps for your application
Body: We enjoyed your profile and would like to invite you for a technical interview.
JSON: {{"category":"INTERVIEW_REQUEST","subcategory":"technical","company_name":"Unknown","job_title":null,"salary_min":null,"salary_max":null,"location":null,"confidence":0.78}}

Email:
Subject: {subject}
From: {sender}
Body: {body_sample}

Return ONLY valid JSON, no other text."""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=450,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return strict JSON only. Do not add markdown or commentary."},
                {"role": "user", "content": prompt},
            ],
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
    return apply_category_overrides(result, subject, body, sender)


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
    prompt = f"""You are an email triage model for job-application workflows.
Return strict JSON only. Do not infer interviews from conditional language like
"if selected for an interview" or "if we move forward" (these are APPLICATION_RECEIVED).

Classify each of the following job application emails and extract structured data.

Category definitions (pick the best match for each email):
- INTERVIEW_REQUEST: Recruiter/company wants to schedule or conduct a full interview (onsite, panel, technical round).
- SCREENING_REQUEST: Recruiter/company wants to schedule a screening call (phone screen, intro call, "15-30 min call", "get to know you", "dates and times that work"). Use for initial recruiter calls before a full interview.
- APPLICATION_RECEIVED: Automated or brief confirmation that your application was received (no interview scheduling).
- RECRUITER_OUTREACH: Unsolicited outreach about a role (you didn't apply yet).
- ASSESSMENT: Coding test, take-home, or assessment invite.
- REJECTION: You are not moving forward / not selected.
- OFFER: Job offer or compensation discussion.
- OTHER: None of the above.

Return a JSON object with a top-level "results" array. Each array item must have exactly these keys (use null for unknown):
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

Return ONLY a valid JSON object with a "results" array of {len(emails)} items, no other text."""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=min(450 * len(emails) + 200, 4096),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return strict JSON only. Do not add markdown or commentary."},
                {"role": "user", "content": prompt},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text).replace("```", "").strip()
        payload = json.loads(text)
        arr = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(arr, list) or len(arr) != len(emails):
            return []
        results = []
        for i, data in enumerate(arr):
            if not isinstance(data, dict):
                r = _parse_single_result({}, *emails[i])
            else:
                r = _parse_single_result(data, *emails[i])
            subject, body, sender = emails[i]
            results.append(apply_category_overrides(r, subject, body, sender))
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


def classify_with_filtering(
    subject: str,
    body: str,
    sender: str,
    skip_non_job: bool = True,
    enhance_extraction: bool = True,
) -> dict:
    """
    Enhanced classification pipeline with filtering and better extraction.

    This is the recommended function for new code. It:
    1. Filters out non-job emails (billing, newsletters, etc.)
    2. Classifies job-related emails
    3. Enhances extraction of company/job title with dedicated LLM calls

    Args:
        subject: Email subject
        body: Email body
        sender: Sender email address
        skip_non_job: If True, return early with is_relevant=False for non-job emails
        enhance_extraction: If True, use enhanced LLM extraction for better company/title

    Returns:
        Dict with:
            - is_relevant: bool (False if not job-related)
            - relevance_confidence: float
            - relevance_reason: str
            - category, subcategory, company_name, job_title, etc. (if relevant)
            - summary, key_points, clean_body (if enhance_extraction=True)
    """
    # Step 1: Check if email is job-related
    is_relevant, rel_confidence, rel_reason = is_job_related_email(subject, body, sender)

    if not is_relevant and skip_non_job:
        return {
            "is_relevant": False,
            "relevance_confidence": rel_confidence,
            "relevance_reason": rel_reason,
            "category": "NOT_JOB_RELATED",
            "subcategory": None,
            "company_name": "Unknown",
            "job_title": None,
            "salary_min": None,
            "salary_max": None,
            "location": None,
            "confidence": None,
        }

    # Step 2: Classify the email
    result = structured_classify_email(subject, body, sender)
    result["is_relevant"] = True
    result["relevance_confidence"] = rel_confidence
    result["relevance_reason"] = rel_reason

    # Step 3: Enhance extraction if needed
    if enhance_extraction:
        result = refine_classification_result(result, subject, body, sender)

    return result


def classify_emails_batch_with_filtering(
    emails: List[Tuple[str, str, str]],
    skip_non_job: bool = True,
    enhance_extraction: bool = True,
) -> List[dict]:
    """
    Batch classify emails with filtering and enhanced extraction.

    Args:
        emails: List of (subject, body, sender) tuples
        skip_non_job: If True, filter out non-job emails
        enhance_extraction: If True, enhance extraction for emails with missing fields

    Returns:
        List of classification results (same length as input, with is_relevant=False for filtered)
    """
    results = []

    # First pass: filter non-job emails using fast rules
    job_email_indices = []
    for i, (subject, body, sender) in enumerate(emails):
        # Use fast rule-based check first
        rule_result = rule_based_relevance_check(subject, body, sender)

        if rule_result is False and skip_non_job:
            # Definitely not job-related
            results.append({
                "is_relevant": False,
                "relevance_confidence": 0.90,
                "relevance_reason": "Matches non-job patterns",
                "category": "NOT_JOB_RELATED",
                "subcategory": None,
                "company_name": "Unknown",
                "job_title": None,
                "salary_min": None,
                "salary_max": None,
                "location": None,
                "confidence": None,
            })
        else:
            # Relevant or uncertain - need classification
            job_email_indices.append(i)
            results.append(None)  # Placeholder

    # Second pass: batch classify job-related emails
    if job_email_indices:
        job_emails = [emails[i] for i in job_email_indices]

        # Try batch classification
        batch_results = structured_classify_emails_batch(job_emails)

        if batch_results and len(batch_results) == len(job_emails):
            for idx, batch_result in zip(job_email_indices, batch_results):
                subject, body, sender = emails[idx]
                batch_result["is_relevant"] = True
                batch_result["relevance_confidence"] = 0.95
                batch_result["relevance_reason"] = "Job-related email"

                if enhance_extraction:
                    batch_result = refine_classification_result(
                        batch_result, subject, body, sender
                    )

                results[idx] = batch_result
        else:
            # Fallback to individual classification
            for idx in job_email_indices:
                subject, body, sender = emails[idx]
                result = classify_with_filtering(
                    subject, body, sender,
                    skip_non_job=skip_non_job,
                    enhance_extraction=enhance_extraction,
                )
                results[idx] = result

    return results
