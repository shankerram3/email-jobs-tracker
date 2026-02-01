"""
LangGraph-powered email classification pipeline.

This module implements a multi-node graph for:
1. Email classification (14 categories)
2. Entity extraction (company, job title, level)
3. Stage assignment (application tracking)
4. Action item detection

Uses OpenAI GPT-4o-mini for inference.
"""
import json
import re
from typing import Optional, List, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from .config import settings
from .job_title_extraction import get_job_title_candidates, pick_best_job_title, clean_job_title, is_plausible_job_title


# =============================================================================
# Email Categories (14 total)
# =============================================================================

EMAIL_CATEGORIES = {
    "job_application_confirmation": "Automated acknowledgment after submitting application",
    "job_rejection": "Rejection notice from company",
    "interview_assessment": "Interview invitations, coding challenges, technical assessments",
    "application_followup": "Requests for additional information (EEO forms, etc.)",
    "recruiter_outreach": "Direct messages from recruiting agencies",
    "talent_community": "Welcome to company talent communities",
    "linkedin_connection_request": "LinkedIn connection invitations",
    "linkedin_message": "LinkedIn direct message notifications",
    "linkedin_job_recommendations": "LinkedIn job alert emails",
    "linkedin_profile_activity": "LinkedIn profile/post engagement notifications",
    "job_alerts": "Job board automated recommendations (Indeed, Glassdoor, etc.)",
    "verification_security": "OTPs, password resets, security codes",
    "promotional_marketing": "Career tips, platform features, marketing",
    "receipts_invoices": "Payment receipts and invoices",
}

# Per-class guidance (key indicators + example snippets) to improve accuracy.
# Keep these compact to avoid prompt bloat.
CLASS_GUIDANCE = {
    "job_application_confirmation": {
        "description": "Automated acknowledgment after submitting a job application",
        "key_indicators": [
            "thank you for applying",
            "received your application",
            "application confirmation",
            "we appreciate your interest",
        ],
        "example": {
            "subject": "Thanks for applying to MyJunior AI!",
            "from": "MyJunior AI Hiring Team <no-reply@ashbyhq.com>",
            "body_snippet": "Thank you for applying for the Senior Full Stack Engineer role at MyJunior AI! We appreciate your interest in joining the team. We will review your application and get back to you if there are next steps.",
        },
    },
    "job_rejection": {
        "description": "Rejection notice from a company after review",
        "key_indicators": [
            "thank you for your interest",
            "not moving forward",
            "do not align with",
            "encourage you to keep an eye",
        ],
        "example": {
            "subject": "Thank you for your interest in Respondology",
            "from": "Mahri Lee <notifications@app.bamboohr.com>",
            "body_snippet": "After reviewing your application, we have determined that your skills and experience do not quite match the requirements for this particular role. We appreciate your interest in our company and encourage you to keep an eye on our career page for future opportunities.",
        },
    },
    "interview_assessment": {
        "description": "Invites to interviews, coding assessments, technical tests, or scheduling calls",
        "key_indicators": [
            "next step",
            "invite you to",
            "assessment",
            "coding challenge",
            "technical evaluation",
            "scheduled for",
        ],
        "example": {
            "subject": "Next Steps with Magic",
            "from": "Magic Hiring Team <no-reply@ashbyhq.com>",
            "body_snippet": "We would like to invite you to the next step of our selection process. Please watch for an email from CodeSignal with your invitation to complete our 90-minute technical assessment.",
        },
    },
    "application_followup": {
        "description": "Requests for additional information/documents/actions after applying",
        "key_indicators": [
            "additional information needed",
            "next steps for your application",
            "EEO self-identification",
            "complete your profile",
            "work opportunity tax credit",
        ],
        "example": {
            "subject": "EEO Self-Identification Form- Talent Software Services, Inc.",
            "from": "humanresources@talentemail.com",
            "body_snippet": "Additional information needed for your application.",
        },
    },
    "recruiter_outreach": {
        "description": "Direct outreach from recruiters/staffing agencies about a role",
        "key_indicators": [
            "must have",
            "key skills",
            "location:",
            "experience:",
            "are you interested",
            "recruiting firm",
        ],
        "example": {
            "subject": "Senior Python / Conversational AI Engineer - remote",
            "from": "Rachit Kumar Bhardwaj <rachit.kumar@diverselynx.com>",
            "body_snippet": "Must have – Python, Conversational AI, NLP, and LLMs. Location: Dallas, TX / Malvern, PA / Remote. Experience: 10+ Years.",
        },
    },
    "talent_community": {
        "description": "Welcome/nurture emails from company talent communities",
        "key_indicators": [
            "welcome to",
            "talent community",
            "join our community",
            "stay connected",
            "job alerts",
        ],
        "example": {
            "subject": "You're in! Welcome to the Mastercard talent community",
            "from": "Mastercard <talent@careers.mastercard.com>",
            "body_snippet": "Welcome to the Mastercard Talent Community. Explore the benefits: Personalized job promos, interview tips, job alerts.",
        },
    },
    "linkedin_connection_request": {
        "description": "LinkedIn connection invitation notifications",
        "key_indicators": [
            "sent you a connection request",
            "I'd like to join your professional network",
            "connections in common",
            "invitations@linkedin.com",
        ],
        "example": {
            "subject": "I've sent you a connection request",
            "from": "Nitin Pandey <invitations@linkedin.com>",
            "body_snippet": "I'd like to join your professional network. Waiting for your response.",
        },
    },
    "linkedin_message": {
        "description": "LinkedIn notifications about new messages",
        "key_indicators": [
            "just messaged you",
            "new message",
            "view message",
            "messaging-digest-noreply@linkedin.com",
        ],
        "example": {
            "subject": "Vikram just messaged you",
            "from": "via LinkedIn <messaging-digest-noreply@linkedin.com>",
            "body_snippet": "You have 1 new message. View message.",
        },
    },
    "linkedin_job_recommendations": {
        "description": "LinkedIn job alert/recommendation emails",
        "key_indicators": [
            "job alert for",
            "jobs in",
            "see all jobs on linkedin",
            "jobalerts-noreply@linkedin.com",
        ],
        "example": {
            "subject": "\"Software Engineer\": Matthews - Software Engineer (PHX) and more",
            "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "body_snippet": "Your job alert for Software Engineer. New jobs match your preferences.",
        },
    },
    "linkedin_profile_activity": {
        "description": "LinkedIn profile/post engagement notifications",
        "key_indicators": [
            "your posts got",
            "views",
            "profile activity",
            "notifications-noreply@linkedin.com",
        ],
        "example": {
            "subject": "last week your posts got 82 views!",
            "from": "LinkedIn <notifications-noreply@linkedin.com>",
            "body_snippet": "See who viewed your posts and track your engagement.",
        },
    },
    "job_alerts": {
        "description": "Automated job recommendations from job boards/platforms",
        "key_indicators": [
            "job alert",
            "new jobs match your preferences",
            "recommended jobs",
            "apply now",
        ],
        "example": {
            "subject": "\"Software Engineer\": NewtonX - Software Engineer- LLM Systems (Remote) and more",
            "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "body_snippet": "Your job alert for Software Engineer. New jobs match your preferences.",
        },
    },
    "verification_security": {
        "description": "OTPs, password resets, verification/security codes",
        "key_indicators": [
            "verification code",
            "OTP",
            "security code",
            "expires in",
            "verify your account",
        ],
        "example": {
            "subject": "Here's your verification code from ADP",
            "from": "SecurityServices_NoReply@adp.com",
            "body_snippet": "Verification code: 356103. This code expires in 15 minutes.",
        },
    },
    "promotional_marketing": {
        "description": "Marketing emails, feature announcements, career tips",
        "key_indicators": [
            "new feature",
            "tips",
            "career advice",
            "discover",
        ],
        "example": {
            "subject": "craft a resume that rises above the noise",
            "from": "LinkedIn <editors-noreply@linkedin.com>",
            "body_snippet": "Tips and tools to improve your resume and stand out to recruiters.",
        },
    },
    "receipts_invoices": {
        "description": "Payment receipts, invoices, transaction confirmations",
        "key_indicators": [
            "receipt",
            "invoice",
            "payment",
            "order confirmation",
            "total amount",
        ],
        "example": {
            "subject": "Your receipt from Wynisco #2026-0074",
            "from": "Wynisco <invoice+statements@stripe.com>",
            "body_snippet": "Receipt for your recent payment.",
        },
    },
}


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip() + "…"


def _build_guidance_text(
    max_indicators: int = 6,
    max_snippet_len: int = 220,
) -> str:
    """Compact few-shot guidance to help the classifier separate similar classes."""
    lines: list[str] = []
    for class_name in EMAIL_CATEGORIES.keys():
        g = CLASS_GUIDANCE.get(class_name)
        if not g:
            continue
        indicators = g.get("key_indicators") or []
        indicators = [str(x) for x in indicators if x]
        indicators = indicators[:max_indicators]
        ex = g.get("example") or {}
        lines.append(f"- {class_name}: {g.get('description','')}".strip())
        if indicators:
            lines.append(f"  indicators: {', '.join(indicators)}")
        subj = _truncate(str(ex.get('subject') or ''), 120)
        frm = _truncate(str(ex.get('from') or ''), 120)
        snippet = _truncate(str(ex.get('body_snippet') or ''), max_snippet_len)
        if subj or frm or snippet:
            lines.append(f"  example: Subject: {subj} | From: {frm} | Snippet: {snippet}")
    return "\n".join(lines).strip()

# Stage mapping for application tracking
STAGE_MAPPING = {
    "job_application_confirmation": "Applied",
    "application_followup": "Applied",
    "interview_assessment": "Interview",
    "recruiter_outreach": "Contacted",
    "job_rejection": "Rejected",
    "talent_community": "Pipeline",
}

# Categories that require user action
ACTION_CATEGORIES = {
    "interview_assessment": ["Complete assessment or schedule interview"],
    "application_followup": ["Submit additional documents"],
    "recruiter_outreach": ["Respond to recruiter"],
}

# Categories to skip entity extraction (not job-related)
SKIP_EXTRACTION_CATEGORIES = {
    "linkedin_connection_request",
    "linkedin_message",
    "linkedin_profile_activity",
    "verification_security",
    "promotional_marketing",
    "receipts_invoices",
}


# =============================================================================
# State Schema
# =============================================================================

class EmailState(TypedDict, total=False):
    """State that flows through the LangGraph pipeline."""
    # Input fields
    email_id: str
    subject: str
    body: str
    sender: str
    received_date: str

    # Classification results
    email_class: str
    confidence: float
    classification_reasoning: str

    # Extracted entities
    company_name: Optional[str]
    job_title: Optional[str]
    position_level: Optional[str]

    # Resume matching (placeholder)
    resume_matched: Optional[str]
    resume_file_id: Optional[str]
    resume_version: Optional[str]

    # Application tracking
    application_stage: str
    requires_action: bool
    action_items: List[str]

    # Processing status
    processing_status: str
    errors: List[str]


# =============================================================================
# OpenAI Client
# =============================================================================

def _get_openai_client():
    """Get OpenAI client instance."""
    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set. Add to .env or environment.")
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _call_llm(prompt: str, max_tokens: int = 500, force_json: bool = False) -> str:
    """Call OpenAI chat model and return response text."""
    client = _get_openai_client()
    # Prefer repo-configured settings when present.
    model = getattr(settings, "openai_model", None) or "gpt-4o-mini"
    temperature = getattr(settings, "openai_temperature", None)
    kwargs = {}
    if isinstance(temperature, (int, float)):
        kwargs["temperature"] = float(temperature)
    else:
        kwargs["temperature"] = 0.1  # Low temp for consistent classification
    if force_json:
        # If supported by the model, this strongly enforces valid JSON output.
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return (response.choices[0].message.content or "").strip()


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    # Remove markdown code blocks if present
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON object from text
        match = re.search(r"\{[\s\S]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


# =============================================================================
# LangGraph Nodes
# =============================================================================

def classify_and_extract_node(state: EmailState) -> dict:
    """
    Combined classification and entity extraction in a single LLM call.
    Reduces latency by ~50% (1 API call instead of 2).
    """
    categories_text = "\n".join(
        f"{i+1}. {name} - {desc}"
        for i, (name, desc) in enumerate(EMAIL_CATEGORIES.items())
    )
    guidance_text = _build_guidance_text()

    subject = state.get("subject", "") or ""
    sender = state.get("sender", "") or ""
    body = state.get("body") or ""
    body_sample = body[:1500]

    # Pre-extract title candidates for context
    title_candidates = get_job_title_candidates(subject=subject, body=body_sample)
    title_candidates_text = "\n".join(f"- {c.value}" for c in title_candidates[:6]) or "- (none found)"

    prompt = f"""You are an email classification and extraction system for job search emails.

TASK 1 - CLASSIFICATION:
Classify this email into EXACTLY ONE of these 14 classes:
{categories_text}

GUIDANCE:
{guidance_text}

PRIORITY RULES:
- interview_assessment > job_application_confirmation (if mentions next steps/assessment)
- job_rejection > talent_community (if clearly rejecting)
- verification_security > application_followup (if contains OTP/code)
- recruiter_outreach > job_alerts (if from a specific recruiter person)

TASK 2 - ENTITY EXTRACTION:
Extract company name, job title, and position level.
For non-job emails (linkedin_*, verification_security, promotional_marketing, receipts_invoices), set all to null.

Possible job title candidates (prefer these when matching):
{title_candidates_text}

EMAIL TO PROCESS:
Subject: {subject}
From: {sender}
Body: {body_sample}

Return ONLY valid JSON (no markdown):
{{
  "email_class": "<class_name from list above>",
  "confidence": <0.0-1.0>,
  "reasoning": "<brief 1-sentence explanation>",
  "company_name": "<company name or null if unclear>",
  "job_title": "<exact job title mentioned or null>",
  "position_level": "<Junior|Mid|Senior|Staff|Principal|Lead|Manager or null>"
}}"""

    try:
        response_text = _call_llm(prompt, max_tokens=350, force_json=True)
        result = _parse_json_response(response_text)

        email_class = (result.get("email_class") or "").strip()
        if email_class not in EMAIL_CATEGORIES:
            email_class = "promotional_marketing"

        # Skip entity processing for non-job categories
        if email_class in SKIP_EXTRACTION_CATEGORIES:
            return {
                "email_class": email_class,
                "confidence": float(result.get("confidence", 0.5)),
                "classification_reasoning": result.get("reasoning", ""),
                "company_name": None,
                "job_title": None,
                "position_level": None,
                "errors": state.get("errors", []),
            }

        # Post-validate job title
        raw_job_title = result.get("job_title")
        job_title = pick_best_job_title(subject=subject, body=body_sample, llm_suggested=raw_job_title)
        job_title = clean_job_title(job_title)
        if job_title and not is_plausible_job_title(job_title):
            job_title = title_candidates[0].value if title_candidates else None

        return {
            "email_class": email_class,
            "confidence": float(result.get("confidence", 0.5)),
            "classification_reasoning": result.get("reasoning", ""),
            "company_name": result.get("company_name"),
            "job_title": job_title,
            "position_level": result.get("position_level"),
            "errors": state.get("errors", []),
        }
    except Exception as e:
        return {
            "email_class": "promotional_marketing",
            "confidence": 0.0,
            "classification_reasoning": f"Processing failed: {str(e)}",
            "company_name": None,
            "job_title": None,
            "position_level": None,
            "errors": state.get("errors", []) + [f"combined_error: {str(e)}"],
        }


def classify_email_node(state: EmailState) -> dict:
    """
    Classify email into one of 14 categories using GPT-4o-mini.
    Returns classification, confidence, and reasoning.
    NOTE: This is the legacy separate classification node. Consider using classify_and_extract_node instead.
    """
    categories_text = "\n".join(
        f"{i+1}. {name} - {desc}"
        for i, (name, desc) in enumerate(EMAIL_CATEGORIES.items())
    )
    guidance_text = _build_guidance_text()

    prompt = f"""You are an email classification system for job search emails.

Classify this email into EXACTLY ONE of these 14 classes:

{categories_text}

GUIDANCE (use as examples and cues):
{guidance_text}

PRIORITY RULES (when multiple classes could apply):
- interview_assessment > job_application_confirmation (if mentions next steps/assessment)
- job_rejection > talent_community (if clearly rejecting)
- verification_security > application_followup (if contains OTP/code)
- recruiter_outreach > job_alerts (if from a specific recruiter person)

EMAIL TO CLASSIFY:
Subject: {state.get('subject', '')}
From: {state.get('sender', '')}
Body: {(state.get('body') or '')[:1500]}

Return ONLY valid JSON (no markdown):
{{
  "email_class": "<class_name from list above>",
  "confidence": <0.0-1.0>,
  "reasoning": "<brief 1-sentence explanation>"
}}"""

    try:
        response_text = _call_llm(prompt, max_tokens=220, force_json=True)
        result = _parse_json_response(response_text)

        email_class = (result.get("email_class") or "").strip()
        # Validate category
        if email_class not in EMAIL_CATEGORIES:
            email_class = "promotional_marketing"  # Default fallback

        return {
            "email_class": email_class,
            "confidence": float(result.get("confidence", 0.5)),
            "classification_reasoning": result.get("reasoning", ""),
            "errors": state.get("errors", []),
        }
    except Exception as e:
        return {
            "email_class": "promotional_marketing",
            "confidence": 0.0,
            "classification_reasoning": f"Classification failed: {str(e)}",
            "errors": state.get("errors", []) + [f"classify_error: {str(e)}"],
        }


def extract_entities_node(state: EmailState) -> dict:
    """
    Extract company name, job title, and position level.
    Skips extraction for non-job-related categories.
    """
    email_class = state.get("email_class", "")

    # Skip extraction for non-job emails
    if email_class in SKIP_EXTRACTION_CATEGORIES:
        return {
            "company_name": None,
            "job_title": None,
            "position_level": None,
        }

    subject = state.get("subject", "") or ""
    sender = state.get("sender", "") or ""
    body = state.get("body") or ""
    body_sample = body[:2000]

    # Deterministic candidates to reduce missing job titles.
    title_candidates = get_job_title_candidates(subject=subject, body=body_sample)
    title_candidates_text = "\n".join(f"- {c.value}" for c in title_candidates[:6]) or "- (none found)"

    prompt = f"""Extract structured information from this job-related email.

Email:
Subject: {subject}
From: {sender}
Body: {body_sample}

Possible job title candidates (auto-extracted; prefer choosing one of these when it matches the email):
{title_candidates_text}

Return ONLY valid JSON (no markdown):
{{
  "company_name": "<company name or null if unclear>",
  "job_title": "<exact job title mentioned or null>",
  "position_level": "<Junior|Mid|Senior|Staff|Principal|Lead|Manager or null>"
}}

Rules:
- For company_name: Extract the hiring company, not job boards or ATS providers
- For job_title: Use the exact title from the email. If the candidates list contains the correct title, return that exact candidate string.
- For job_title: Do NOT include extra text like "role", "position", "opportunity", or "at <company>".
- For position_level: Infer from title if not explicit (e.g., "Senior" from "Senior Engineer")
- Use null (not "null" string) if information is not present"""

    try:
        response_text = _call_llm(prompt, max_tokens=200, force_json=True)
        entities = _parse_json_response(response_text)

        # Post-validate / fallback for job_title to reduce missing titles.
        raw_job_title = entities.get("job_title")
        job_title = pick_best_job_title(subject=subject, body=body_sample, llm_suggested=raw_job_title)
        # If the model returned something, keep it only if plausible; otherwise fallback already applied.
        job_title = clean_job_title(job_title)
        if job_title and not is_plausible_job_title(job_title):
            job_title = title_candidates[0].value if title_candidates else None

        return {
            "company_name": entities.get("company_name"),
            "job_title": job_title,
            "position_level": entities.get("position_level"),
        }
    except Exception as e:
        errors = state.get("errors", []) + [f"extract_error: {str(e)}"]
        return {
            "company_name": None,
            "job_title": None,
            "position_level": None,
            "errors": errors,
        }


def match_resume_node(state: EmailState) -> dict:
    """
    Placeholder for resume matching.
    In the future, this will query Google Drive for matching resumes.
    """
    email_class = state.get("email_class", "")

    # Only match for application-related emails
    match_classes = {
        "job_application_confirmation",
        "job_rejection",
        "interview_assessment",
        "application_followup",
    }

    if email_class not in match_classes:
        return {
            "resume_matched": None,
            "resume_file_id": None,
            "resume_version": None,
        }

    # Placeholder: In future, query database/Drive for matching resume
    # For now, return None (no match)
    return {
        "resume_matched": None,
        "resume_file_id": None,
        "resume_version": None,
    }


def assign_stage_node(state: EmailState) -> dict:
    """
    Map email class to application stage and determine required actions.
    """
    email_class = state.get("email_class", "")

    # Get application stage
    stage = STAGE_MAPPING.get(email_class, "Other")

    # Offer detection: keep the 14 classes, but set stage=Offer when clearly an offer.
    subject = state.get("subject", "") or ""
    body = state.get("body", "") or ""
    combined = f"{subject}\n{body}".lower()
    # Screening detection (subset of interview_assessment): phone screens / recruiter screens.
    screening_phrases = [
        "phone screen",
        "screening call",
        "recruiter screen",
        "intro call",
        "introductory call",
        "15 min call",
        "30 min call",
        "schedule a call",
        "available for a call",
    ]
    is_screening = email_class == "interview_assessment" and any(p in combined for p in screening_phrases)
    if is_screening:
        stage = "Screening"

    offer_phrases = [
        "we're pleased to offer",
        "we are pleased to offer",
        "we'd like to offer",
        "we would like to offer",
        "extend an offer",
        "offer letter",
        "employment offer",
        "compensation package",
        "salary offer",
        "congratulations",
    ]
    is_offer = any(p in combined for p in offer_phrases)
    if is_offer:
        stage = "Offer"

    # Determine if action required
    requires_action = email_class in ACTION_CATEGORIES
    action_items = ACTION_CATEGORIES.get(email_class, [])
    if is_offer:
        requires_action = True
        action_items = list(action_items) + ["Review offer details and respond"]

    return {
        "application_stage": stage,
        "requires_action": requires_action,
        "action_items": action_items,
        "processing_status": "completed",
    }


# =============================================================================
# Graph Construction
# =============================================================================

def create_email_processing_graph(use_combined_node: bool = True) -> Any:
    """
    Build the complete email processing workflow.

    Args:
        use_combined_node: If True (default), uses single LLM call for classify+extract.
                          If False, uses separate nodes (2 LLM calls).

    Flow (combined): START -> classify_and_extract -> match_resume -> assign_stage -> END
    Flow (separate): START -> classify -> extract_entities -> match_resume -> assign_stage -> END
    """
    graph = StateGraph(EmailState)

    if use_combined_node:
        # Optimized: Single LLM call for classification + extraction (50% faster)
        graph.add_node("classify_and_extract", classify_and_extract_node)
        graph.add_node("match_resume", match_resume_node)
        graph.add_node("assign_stage", assign_stage_node)

        graph.add_edge(START, "classify_and_extract")
        graph.add_edge("classify_and_extract", "match_resume")
        graph.add_edge("match_resume", "assign_stage")
        graph.add_edge("assign_stage", END)
    else:
        # Legacy: Separate nodes (2 LLM calls)
        graph.add_node("classify", classify_email_node)
        graph.add_node("extract_entities", extract_entities_node)
        graph.add_node("match_resume", match_resume_node)
        graph.add_node("assign_stage", assign_stage_node)

        graph.add_edge(START, "classify")
        graph.add_edge("classify", "extract_entities")
        graph.add_edge("extract_entities", "match_resume")
        graph.add_edge("match_resume", "assign_stage")
        graph.add_edge("assign_stage", END)

    # Compile the graph
    return graph.compile()


# Create singleton instance
email_classifier_graph = create_email_processing_graph()


# =============================================================================
# Public API
# =============================================================================

def process_email(
    email_id: str,
    subject: str,
    body: str,
    sender: str,
    received_date: str = "",
) -> EmailState:
    """
    Process a single email through the LangGraph pipeline.

    Args:
        email_id: Unique identifier (e.g., Gmail message ID)
        subject: Email subject line
        body: Email body text
        sender: Sender email address
        received_date: ISO format date string

    Returns:
        EmailState with all classification and extraction results
    """
    initial_state: EmailState = {
        "email_id": email_id,
        "subject": subject,
        "body": body,
        "sender": sender,
        "received_date": received_date,
        "errors": [],
    }

    # Run through graph
    result = email_classifier_graph.invoke(initial_state)
    return result


def get_category_display_name(category: str) -> str:
    """Get human-readable name for a category."""
    return EMAIL_CATEGORIES.get(category, category.replace("_", " ").title())


def get_all_categories() -> dict:
    """Return all available categories with descriptions."""
    return EMAIL_CATEGORIES.copy()


# =============================================================================
# Batch Processing API
# =============================================================================

def _process_batch_llm(emails: List[dict]) -> List[dict]:
    """
    Single LLM call for batch classification+extraction.

    Args:
        emails: List of dicts with keys: email_id, subject, body, sender, received_date

    Returns:
        List of result dicts (one per email) or empty list on failure
    """
    if not emails:
        return []

    categories_text = "\n".join(
        f"- {name}: {desc}" for name, desc in EMAIL_CATEGORIES.items()
    )

    email_parts = []
    for i, e in enumerate(emails):
        body_sample = (e.get("body") or "")[:1200]
        email_parts.append(
            f"--- Email {i+1} ---\n"
            f"Subject: {e.get('subject', '')}\n"
            f"From: {e.get('sender', '')}\n"
            f"Body: {body_sample}"
        )

    combined = "\n\n".join(email_parts)

    prompt = f"""You are an email classification and extraction system for job search emails.

Categories (choose exactly one per email):
{categories_text}

PRIORITY RULES (when multiple categories could apply):
- interview_assessment > job_application_confirmation (if mentions next steps/assessment/coding challenge)
- job_rejection > talent_community (if clearly rejecting with "not moving forward", "unfortunately")
- verification_security > application_followup (if contains OTP/verification code)
- recruiter_outreach > job_alerts (if from a specific recruiter person, not automated)

For each email, determine:
1. email_class: One of the categories above (be precise - rejections and interviews are critical)
2. confidence: 0.0-1.0 (use lower confidence if uncertain between categories)
3. reasoning: Brief explanation of why this category
4. company_name: The HIRING company (not LinkedIn, Indeed, Greenhouse, or other platforms)
5. job_title: Exact job title mentioned (not "opportunity" or "role")
6. position_level: Junior|Mid|Senior|Staff|Principal|Lead|Manager or null

Return a JSON object with a "results" array containing exactly {len(emails)} items in order.

Emails to process:
{combined}

Return ONLY valid JSON:
{{"results": [...]}}"""

    try:
        # Calculate max tokens: ~350 per email + overhead
        max_tokens = min(350 * len(emails) + 200, 4096)
        response = _call_llm(prompt, max_tokens=max_tokens, force_json=True)
        data = _parse_json_response(response)
        arr = data.get("results", [])

        if not isinstance(arr, list) or len(arr) != len(emails):
            return []

        return arr
    except Exception:
        return []


def process_emails_batch(
    emails: List[dict],
    batch_size: int = 10,
    confidence_threshold: float = 0.6,
) -> List[EmailState]:
    """
    Process multiple emails efficiently using batch LLM calls.

    For accuracy preservation:
    - Low-confidence results (< threshold) are reprocessed individually
    - Critical categories (rejection, offer) are validated more strictly
    - Job titles are post-validated against extracted candidates

    Args:
        emails: List of dicts with keys: email_id, subject, body, sender, received_date
        batch_size: Number of emails per LLM call (default 10)
        confidence_threshold: Minimum confidence to accept batch result (default 0.6)

    Returns:
        List of EmailState results (one per input email)
    """
    if not emails:
        return []

    if batch_size <= 1:
        # Fall back to individual processing
        return [process_email(**e) for e in emails]

    # Categories that are critical and should be reprocessed if low confidence
    CRITICAL_CATEGORIES = {
        "job_rejection",
        "interview_assessment",
        "job_application_confirmation",
    }

    results: List[EmailState] = []

    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        batch_results = _process_batch_llm(batch)

        if batch_results and len(batch_results) == len(batch):
            # Process each result through remaining pipeline stages
            for email_data, llm_result in zip(batch, batch_results):
                # Validate email_class
                email_class = (llm_result.get("email_class") or "").strip()
                if email_class not in EMAIL_CATEGORIES:
                    email_class = "promotional_marketing"

                confidence = float(llm_result.get("confidence", 0.5))

                # Accuracy safeguard: reprocess low-confidence critical emails individually
                if confidence < confidence_threshold and email_class in CRITICAL_CATEGORIES:
                    # Fall back to individual processing for better accuracy
                    results.append(process_email(**email_data))
                    continue

                # Build initial state with LLM results
                state: EmailState = {
                    "email_id": email_data.get("email_id", ""),
                    "subject": email_data.get("subject", ""),
                    "body": email_data.get("body", ""),
                    "sender": email_data.get("sender", ""),
                    "received_date": email_data.get("received_date", ""),
                    "email_class": email_class,
                    "confidence": confidence,
                    "classification_reasoning": llm_result.get("reasoning", ""),
                    "company_name": llm_result.get("company_name"),
                    "job_title": llm_result.get("job_title"),
                    "position_level": llm_result.get("position_level"),
                    "errors": [],
                }

                # Post-validate job title
                if email_class not in SKIP_EXTRACTION_CATEGORIES:
                    subject = email_data.get("subject", "") or ""
                    body_sample = (email_data.get("body") or "")[:1500]
                    title_candidates = get_job_title_candidates(subject=subject, body=body_sample)

                    raw_job_title = state.get("job_title")
                    job_title = pick_best_job_title(subject=subject, body=body_sample, llm_suggested=raw_job_title)
                    job_title = clean_job_title(job_title)
                    if job_title and not is_plausible_job_title(job_title):
                        job_title = title_candidates[0].value if title_candidates else None
                    state["job_title"] = job_title

                # Run through remaining pipeline stages (no LLM calls)
                state = {**state, **match_resume_node(state)}
                state = {**state, **assign_stage_node(state)}

                results.append(state)
        else:
            # Fallback to individual processing for this batch
            for email_data in batch:
                results.append(process_email(**email_data))

    return results
