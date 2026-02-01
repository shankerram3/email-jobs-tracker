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
# Classification Guards (Rule-Based Overrides)
# =============================================================================

def _has_conditional_interview_language(text: str) -> bool:
    """
    Detect conditional interview language that should NOT be classified as interview.

    Phrases like "if selected for an interview" are acknowledgments about POTENTIAL
    future interviews, not actual interview invitations.
    """
    conditional_phrases = [
        r"if\s+(?:you(?:'|')?re|we(?:'|')?re)\s+selected\s+for\s+an?\s+interview",
        r"if\s+selected\s+for\s+an?\s+interview",
        r"if\s+we\s+decide\s+to\s+move\s+forward",
        r"if\s+we\s+move\s+forward",
        r"should\s+you\s+advance",
        r"if\s+chosen\s+to\s+move\s+forward",
        r"if\s+there\s+(?:is|are)\s+(?:a\s+)?(?:potential\s+)?(?:fit|match)",
        r"we(?:'|')?ll\s+(?:be\s+in\s+touch|reach\s+out|contact\s+you)\s+if",
    ]
    return any(re.search(p, text.lower()) for p in conditional_phrases)


def _has_rejection_language(text: str) -> bool:
    """
    Detect rejection language that should override confirmation classification.

    Even if an email starts with "thank you for your interest", rejection phrases
    indicate this is a rejection, not a confirmation.
    """
    rejection_phrases = [
        r"unfortunately",
        r"regret\s+to\s+inform",
        r"not\s+moving\s+forward",
        r"will\s+not\s+be\s+moving\s+forward",
        r"not\s+selected",
        r"position\s+has\s+been\s+filled",
        r"decided\s+to\s+(?:move\s+forward\s+with|pursue)\s+other\s+candidates?",
        r"not\s+(?:quite\s+)?match(?:ing)?\s+(?:the\s+)?requirements?",
        r"we\s+will\s+not\s+proceed",
        r"do\s+not\s+align\s+with",
        r"after\s+careful\s+(?:review|consideration)",
        r"competitive\s+(?:applicant\s+)?pool",
        r"won(?:'|')?t\s+be\s+(?:moving|proceeding)",
        r"not\s+(?:the\s+)?right\s+fit",
        r"unable\s+to\s+(?:move|proceed)\s+forward",
    ]
    return any(re.search(p, text.lower()) for p in rejection_phrases)


def _has_actual_interview_invitation(text: str) -> bool:
    """
    Detect actual interview invitations (not conditional).

    These are concrete next steps, not conditional possibilities.
    """
    interview_phrases = [
        r"(?:we(?:'|')?d\s+like\s+to|we\s+would\s+like\s+to)\s+(?:invite|schedule)",
        r"please\s+(?:schedule|book|complete)\s+(?:your|the|an?)\s+(?:interview|assessment)",
        r"(?:interview|assessment)\s+(?:is\s+)?scheduled\s+for",
        r"(?:coding|technical)\s+(?:challenge|assessment|test)",
        r"hackerrank|codesignal|codility|leetcode",
        r"take[-\s]?home\s+(?:assignment|project|test)",
        r"next\s+step(?:s)?\s+(?:is|are|in)\s+(?:your|the|our)",
    ]
    return any(re.search(p, text.lower()) for p in interview_phrases)


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

# Per-class guidance (key indicators + negative indicators + example snippets) to improve accuracy.
# Keep these compact to avoid prompt bloat.
CLASS_GUIDANCE = {
    "job_application_confirmation": {
        "description": "Automated acknowledgment emails received after submitting a job application",
        "key_indicators": [
            "thank you for applying",
            "received your application",
            "application confirmation",
            "we appreciate your interest",
            "application submitted",
            "we'll review your application",
        ],
        "negative_indicators": [
            "unfortunately",
            "not moving forward",
            "coding challenge",
            "assessment",
            "schedule an interview",
            "invite you to interview",
        ],
        "example": {
            "subject": "Thanks for applying to MyJunior AI!",
            "from": "MyJunior AI Hiring Team <no-reply@ashbyhq.com>",
            "body_snippet": "Thank you for applying for the Senior Full Stack Engineer role at MyJunior AI! We appreciate your interest in joining the team. We will review your application and get back to you if there are next steps.",
        },
    },
    "job_rejection": {
        "description": "Rejection emails from companies after application review, indicating the candidate will not move forward",
        "key_indicators": [
            "thank you for your interest",
            "not quite match the requirements",
            "not moving forward",
            "do not align with",
            "encourage you to keep an eye",
            "unfortunately",
            "after careful consideration",
            "competitive applicant pool",
            "decided to pursue other candidates",
            "position has been filled",
        ],
        "negative_indicators": [
            "next steps",
            "schedule",
            "assessment",
            "interview invitation",
        ],
        "example": {
            "subject": "Thank you for your interest in Respondology",
            "from": "Mahri Lee <notifications@app.bamboohr.com>",
            "body_snippet": "After reviewing your application, we have determined that your skills and experience do not quite match the requirements for this particular role. We appreciate your interest in our company and encourage you to keep an eye on our career page for future opportunities.",
        },
    },
    "interview_assessment": {
        "description": "Emails inviting candidates to interviews, coding assessments, technical tests, or scheduling interview calls",
        "key_indicators": [
            "next step",
            "invite you to",
            "assessment",
            "coding challenge",
            "technical evaluation",
            "interview",
            "scheduled for",
            "HackerRank",
            "CodeSignal",
            "Codility",
            "take-home",
        ],
        "negative_indicators": [
            "if selected for an interview",
            "if we decide to move forward",
            "unfortunately",
            "not moving forward",
        ],
        "example": {
            "subject": "Next Steps with Magic",
            "from": "Magic Hiring Team <no-reply@ashbyhq.com>",
            "body_snippet": "Thank you for applying for the Software Engineer - Product role at Magic! We would like to invite you to the next step of our selection process. Please watch for an email from CodeSignal with your invitation to complete our 90-minute technical assessment. Block 90 minutes (uninterrupted) where you can focus on completing coding tasks.",
        },
    },
    "application_followup": {
        "description": "Requests for additional information, documents, or actions after initial application",
        "key_indicators": [
            "additional information needed",
            "next steps for your application",
            "EEO self-identification",
            "complete your profile",
            "work opportunity tax credit",
        ],
        "negative_indicators": [
            "coding challenge",
            "assessment",
            "interview",
        ],
        "example": {
            "subject": "EEO Self-Identification Form- Talent Software Services, Inc.",
            "from": "humanresources@talentemail.com",
            "body_snippet": "Additional information needed for your application.",
        },
    },
    "recruiter_outreach": {
        "description": "Direct outreach from recruiters or staffing agencies about specific job opportunities",
        "key_indicators": [
            "must have",
            "key skills",
            "location:",
            "experience:",
            "are you interested",
            "staffing",
            "recruiting firm",
            "came across your profile",
            "noticed your background",
        ],
        "negative_indicators": [
            "thank you for applying",
            "received your application",
        ],
        "example": {
            "subject": "Senior Python / Conversational AI Engineer - remote",
            "from": "Rachit Kumar Bhardwaj <rachit.kumar@diverselynx.com>",
            "body_snippet": "Senior Python / Conversational AI Engineer / NLP Analyst. Must have – Python, Conversational AI, NLP, and LLMs. Location: Dallas, TX / Malvern, PA / Remote. Experience: 10+ Years. Key Skills: Strong Python development, Experience in Conversational AI, NLP, and LLMs, Hands-on with TensorFlow, PyTorch, Hugging Face.",
        },
    },
    "talent_community": {
        "description": "Welcome emails and nurture campaigns from company talent communities",
        "key_indicators": [
            "welcome to",
            "talent community",
            "join our community",
            "stay connected",
            "personalized job",
            "exclusive",
        ],
        "negative_indicators": [
            "unfortunately",
            "not moving forward",
            "not selected",
        ],
        "example": {
            "subject": "You're in! Welcome to the Mastercard talent community",
            "from": "Mastercard <talent@careers.mastercard.com>",
            "body_snippet": "Welcome to the Mastercard Talent Community, Ram! By joining our talent community, you're stepping into a world where bold ideas come together. Explore the benefits: Personalized job promos, Ace your interviews with exclusive tips and resources, Enable job alerts.",
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
        "negative_indicators": [],
        "example": {
            "subject": "I've sent you a connection request",
            "from": "Nitin Pandey <invitations@linkedin.com>",
            "body_snippet": "Nitin, Director Talent Acquisition from Emonics LLC is waiting for your response. Hi Ram, I'd like to join your professional network. Nitin Pandey - Full-Time Placement | Managing Fulltime Recruitment Life Cycle. 3 connections in common.",
        },
    },
    "linkedin_message": {
        "description": "Notifications about new messages received on LinkedIn",
        "key_indicators": [
            "just messaged you",
            "new message",
            "messaging-digest-noreply@linkedin.com",
            "view message",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "Vikram just messaged you",
            "from": "Vikram Arikath via LinkedIn <messaging-digest-noreply@linkedin.com>",
            "body_snippet": "You have 1 new message. Vikram Arikath (Senior Business Analyst at The Aspen Group I Data Analysis…). View message: [link]",
        },
    },
    "linkedin_job_recommendations": {
        "description": "LinkedIn's curated job suggestions and career-related notifications",
        "key_indicators": [
            "jobs in [location] for you",
            "job alert for",
            "jobalerts-noreply@linkedin.com",
            "see all jobs on linkedin",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "\"Software Engineer\": Matthews™ - Software Engineer (PHX) and more",
            "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "body_snippet": "Your job alert for Software Engineer in Phoenix, AZ. New jobs match your preferences.",
        },
    },
    "linkedin_profile_activity": {
        "description": "LinkedIn notifications about profile views, post engagement, and platform activity",
        "key_indicators": [
            "your posts got",
            "views",
            "follow",
            "profile activity",
            "notifications-noreply@linkedin.com",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "Ram, last week your posts got 82 views!",
            "from": "LinkedIn <notifications-noreply@linkedin.com>",
            "body_snippet": "See who viewed your posts and track your engagement.",
        },
    },
    "job_alerts": {
        "description": "Automated job recommendation emails from job boards and platforms suggesting relevant positions",
        "key_indicators": [
            "job alert",
            "new jobs match your preferences",
            "jobs in [location] for you",
            "recommended jobs",
            "apply now",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "\"Software Engineer\": NewtonX - Software Engineer- LLM Systems (Remote) and more",
            "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "body_snippet": "Your job alert for Software Engineer in United States. New jobs match your preferences. Software Engineer- LLM Systems (Remote) at NewtonX - United States - Fast growing. Software Engineers (Remote) at Keystone Recruitment. Backend Engineer II at Openly.",
        },
    },
    "verification_security": {
        "description": "Security codes, OTPs, password resets, and account verification emails",
        "key_indicators": [
            "verification code",
            "OTP",
            "security code",
            "password setup",
            "verify your account",
            "expires in",
            "one-time password",
            "2FA",
            "sign-in code",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "Here's your verification code from ADP",
            "from": "SecurityServices_NoReply@adp.com",
            "body_snippet": "Verification code: 356103. This code expires in 15 minutes. Enter this code to access ADP services.",
        },
    },
    "promotional_marketing": {
        "description": "Marketing emails, feature announcements, and promotional content from job platforms",
        "key_indicators": [
            "new feature",
            "tips",
            "career advice",
            "learning spotlight",
            "check out",
            "discover",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "Ram, craft a resume that rises above the noise",
            "from": "LinkedIn <editors-noreply@linkedin.com>",
            "body_snippet": "Tips and tools to improve your resume and stand out to recruiters.",
        },
    },
    "receipts_invoices": {
        "description": "Payment receipts, invoices, and financial transaction confirmations",
        "key_indicators": [
            "receipt",
            "invoice",
            "payment",
            "order confirmation",
            "@stripe.com",
            "total amount",
        ],
        "negative_indicators": [],
        "example": {
            "subject": "Your receipt from Wynisco #2026-0074",
            "from": "Wynisco <invoice+statements+acct_1HeMfYFqP09V28F5@stripe.com>",
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
    max_neg_indicators: int = 3,
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
        neg_indicators = g.get("negative_indicators") or []
        neg_indicators = [str(x) for x in neg_indicators if x]
        neg_indicators = neg_indicators[:max_neg_indicators]
        ex = g.get("example") or {}
        lines.append(f"- {class_name}: {g.get('description','')}".strip())
        if indicators:
            lines.append(f"  LOOK FOR: {', '.join(indicators)}")
        if neg_indicators:
            lines.append(f"  NOT IF: {', '.join(neg_indicators)}")
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
    needs_review: bool  # Flag for low-confidence classifications

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

def classify_email_node(state: EmailState) -> dict:
    """
    Classify email into one of 14 categories using GPT-4o-mini.
    Returns classification, confidence, reasoning, and needs_review flag.

    Applies rule-based guards to correct common misclassifications:
    - Conditional interview language -> job_application_confirmation
    - Rejection language in confirmations -> job_rejection
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

CRITICAL DISAMBIGUATION RULES:
1. CONDITIONAL LANGUAGE = job_application_confirmation (NOT interview_assessment)
   - "if selected for an interview" = NOT an interview invite
   - "if we decide to move forward" = NOT an interview invite
   - "we'll be in touch if there's a fit" = NOT an interview invite
   - These are acknowledgments with conditional future possibilities

2. REJECTION LANGUAGE = job_rejection (even with polite phrases)
   - "unfortunately" = REJECTION
   - "not moving forward" = REJECTION
   - "position has been filled" = REJECTION
   - "decided to pursue other candidates" = REJECTION
   - "thank you for your interest" + any rejection phrase = REJECTION

3. ACTUAL INTERVIEW = interview_assessment
   - "we'd like to schedule an interview" = interview
   - "please complete this assessment" = interview_assessment
   - "your interview is scheduled for" = interview_assessment
   - Must have CONCRETE next step, not conditional

PRIORITY RULES (when multiple classes could apply):
- job_rejection > job_application_confirmation (if ANY rejection language present)
- job_rejection > talent_community (if clearly rejecting)
- interview_assessment > job_application_confirmation (ONLY if concrete interview/assessment, not conditional)
- verification_security > application_followup (if contains OTP/code)
- recruiter_outreach > job_alerts (if from a specific recruiter person)
- application_followup > job_application_confirmation (if requests documents/forms)

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

    subject = state.get('subject', '') or ''
    body = state.get('body', '') or ''
    combined_text = f"{subject}\n{body}".lower()

    try:
        response_text = _call_llm(prompt, max_tokens=220, force_json=True)
        result = _parse_json_response(response_text)

        email_class = (result.get("email_class") or "").strip()
        confidence = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "")

        # Validate category
        if email_class not in EMAIL_CATEGORIES:
            email_class = "promotional_marketing"  # Default fallback

        # =================================================================
        # Apply rule-based guards to correct common misclassifications
        # =================================================================

        # Guard 1: Rejection language should override confirmation/talent_community
        if email_class in ("job_application_confirmation", "talent_community"):
            if _has_rejection_language(combined_text):
                email_class = "job_rejection"
                reasoning = f"[Override: rejection language detected] {reasoning}"

        # Guard 2: Conditional interview language should NOT be interview_assessment
        if email_class == "interview_assessment":
            if _has_conditional_interview_language(combined_text):
                # Only override if there's NO actual interview invitation
                if not _has_actual_interview_invitation(combined_text):
                    email_class = "job_application_confirmation"
                    reasoning = f"[Override: conditional language, no concrete invite] {reasoning}"

        # Calculate needs_review flag for low-confidence classifications
        needs_review = confidence < 0.65

        return {
            "email_class": email_class,
            "confidence": confidence,
            "classification_reasoning": reasoning,
            "needs_review": needs_review,
            "errors": state.get("errors", []),
        }
    except Exception as e:
        return {
            "email_class": "promotional_marketing",
            "confidence": 0.0,
            "classification_reasoning": f"Classification failed: {str(e)}",
            "needs_review": True,  # Flag failed classifications for review
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

def create_email_processing_graph() -> Any:
    """
    Build the complete email processing workflow.

    Flow: START -> classify -> extract_entities -> match_resume -> assign_stage -> END
    """
    graph = StateGraph(EmailState)

    # Add nodes
    graph.add_node("classify", classify_email_node)
    graph.add_node("extract_entities", extract_entities_node)
    graph.add_node("match_resume", match_resume_node)
    graph.add_node("assign_stage", assign_stage_node)

    # Define edges (linear flow for now)
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
