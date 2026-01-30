"""
Job title extraction utilities.

Goal: improve recall (avoid missing titles) while keeping the title "exact-ish"
as written in the email, with only obvious wrapper/noise removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class TitleCandidate:
    value: str
    score: int
    source: str  # e.g. "subject:pattern1"


def _collapse_ws(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def clean_job_title(raw: Optional[str]) -> Optional[str]:
    """
    Clean a raw extracted title while keeping it close to the email's wording.
    Removes obvious wrappers like "role:" and suffixes like "at Company".
    """
    if not raw:
        return None
    s = _collapse_ws(raw)
    if not s:
        return None

    # Strip surrounding quotes/brackets.
    s = s.strip(" \t\r\n\"'“”‘’`")

    # Remove common wrappers/prefixes.
    s = re.sub(r"^(?:the\s+)?(?:role|position|title|opening|opportunity)\s*[:\-–—]\s*", "", s, flags=re.I)
    s = re.sub(r"^job\s*title\s*[:\-–—]\s*", "", s, flags=re.I)

    # Remove common suffixes that often follow a title.
    s = re.sub(r"\s+(?:role|position)\s*$", "", s, flags=re.I)

    # Remove trailing "at <company>" or "with <company>" when it looks like a suffix.
    s = re.sub(r"\s+(?:at|with)\s+[A-Z0-9][\w&.,'\- ]{1,80}\s*$", "", s).strip()

    # Strip quotes again in case they wrapped the title and a suffix was removed.
    s = s.strip(" \t\r\n\"'“”‘’`")

    # Remove requisition IDs / tracking tokens like "(Req 12345)" or "[Req #A-7788]".
    s = re.sub(
        r"\s*[\(\[\{]\s*(?:req(?:uisition)?|job|role)?\s*#?\s*[A-Z0-9][\w\-]*\s*[\)\]\}]\s*$",
        "",
        s,
        flags=re.I,
    ).strip()
    s = re.sub(r"\s*-\s*(?:Req|Requisition)\s*#?\s*[A-Z0-9][\w\-]*\s*$", "", s, flags=re.I).strip()

    # Remove trailing punctuation.
    s = s.rstrip(" .,:;|/\\-–—")

    s = _collapse_ws(s)
    return s or None


def is_plausible_job_title(title: Optional[str]) -> bool:
    """
    Conservative plausibility filter: prevent obvious junk, but keep recall high.
    """
    if not title:
        return False
    s = _collapse_ws(title)
    if not (3 <= len(s) <= 90):
        return False

    # Must contain at least one letter.
    if not re.search(r"[A-Za-z]", s):
        return False

    # Avoid URLs/emails.
    if re.search(r"https?://|www\.", s, re.I):
        return False
    if re.search(r"\b[\w.\-]+@[\w.\-]+\.\w+\b", s):
        return False

    # Too many words is usually a sentence, not a title.
    if len(s.split()) > 10:
        return False

    # Known non-titles / boilerplate.
    lowered = s.lower()
    banned = (
        "thank you for applying",
        "your application",
        "next steps",
        "application received",
        "interview invitation",
        "candidate",
        "opportunity",
        "position",
        "role",
        "job",
    )
    if lowered in banned:
        return False

    return True


def _dedupe_keep_best(cands: Iterable[TitleCandidate]) -> list[TitleCandidate]:
    best: dict[str, TitleCandidate] = {}
    for c in cands:
        key = _collapse_ws(c.value).lower()
        existing = best.get(key)
        if existing is None or c.score > existing.score:
            best[key] = c
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


def _extract_with_patterns(text: str, patterns: Sequence[tuple[str, int, str]]) -> list[TitleCandidate]:
    out: list[TitleCandidate] = []
    for pat, score, source_tag in patterns:
        m = re.search(pat, text or "", flags=re.I | re.M)
        if not m:
            continue
        raw = m.group(1) if m.lastindex else m.group(0)
        cleaned = clean_job_title(raw)
        if is_plausible_job_title(cleaned):
            out.append(TitleCandidate(value=cleaned, score=score, source=source_tag))
    return out


def get_job_title_candidates(
    *,
    subject: str,
    body: str,
    max_body_chars: int = 2500,
) -> list[TitleCandidate]:
    """
    Extract ranked job title candidates from subject + body.

    Subject is prioritized because it's often the cleanest source.
    """
    subject = subject or ""
    body = (body or "")[:max_body_chars]

    # Subject patterns (higher confidence)
    subject_patterns: list[tuple[str, int, str]] = [
        # "Interview invitation for Senior Software Engineer"
        (r"\b(?:interview|phone\s*screen|screening)\b.*?\bfor\b\s+(.+?)\s*$", 120, "subject:interview_for"),
        # "Application received - Senior Backend Engineer"
        (r"\b(?:application|applied|thanks\s+for\s+applying|thank\s+you\s+for\s+applying)\b.*?(?:for|-\s*)\s+(.+?)\s*$", 110, "subject:applied_for"),
        # "Senior Python Engineer - Remote - Company"
        (r"^\s*([A-Za-z][^|]{3,80}?)\s+[-–—]\s+(?:remote|hybrid|onsite)\b", 105, "subject:title_dash_location"),
        # "Role: Senior Data Engineer"
        (r"\b(?:role|position|title|opening|opportunity)\s*[:\-–—]\s*(.+?)\s*$", 100, "subject:role_label"),
        # "Senior Data Engineer at Acme"
        (r"^\s*(.+?)\s+\b(?:at|with)\b\s+[A-Z0-9]", 95, "subject:title_at_company"),
    ]

    # Body patterns (lower confidence; still useful for missing-title cases)
    body_patterns: list[tuple[str, int, str]] = [
        # "Thank you for applying for the Senior Full Stack Engineer role at X"
        (r"thank you for applying for (?:the )?(.+?)(?:\s+(?:role|position))?\s+(?:at|with)\b", 90, "body:thanks_for_applying"),
        # "Your application for Senior Backend Engineer"
        (r"\byour application (?:was received|for)\s*(?:for\s+)?(.+?)\s*(?:\n|\.|,|$)", 80, "body:your_application_for"),
        # "We would like to invite you to interview for Senior Backend Engineer"
        (r"\binvit(?:e|ing)\s+you\b.*?\bfor\b\s+(.+?)\s*(?:\n|\.|,|$)", 75, "body:invite_for"),
        # "Position: Senior Backend Engineer"
        (r"\b(?:position|role|job title|title|hiring)\s*[:\-–—]\s*(.+?)\s*(?:\n|\.|,|$)", 70, "body:label"),
    ]

    cands: list[TitleCandidate] = []
    cands.extend(_extract_with_patterns(subject, subject_patterns))
    cands.extend(_extract_with_patterns(body, body_patterns))
    return _dedupe_keep_best(cands)


def pick_best_job_title(
    *,
    subject: str,
    body: str,
    llm_suggested: Optional[str] = None,
) -> Optional[str]:
    """
    Given an optional model-suggested title, return a best-effort title.
    Prefer the model output if it looks plausible; otherwise use the top candidate.
    """
    suggested = clean_job_title(llm_suggested)
    if is_plausible_job_title(suggested):
        return suggested

    cands = get_job_title_candidates(subject=subject, body=body)
    return cands[0].value if cands else None

