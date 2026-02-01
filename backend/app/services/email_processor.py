"""Background email sync: history-based incremental, LangGraph classification, caching, duplicate detection."""
import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Callable, Optional, List, Tuple
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from ..gmail_service import (
    get_gmail_service,
    fetch_emails,
    fetch_emails_from_history,
    get_profile_history_id,
    email_to_parts,
)
from ..config import settings
from ..models import Application, EmailLog, SyncMetadata, SyncState, ClassificationCache
from ..sync_state_db import (
    get_sync_state,
    get_last_history_id,
    set_last_history_id,
    set_last_full_sync_at,
    set_memory_progress,
)
from .classification_service import normalize_company_with_db
from ..email_classifier import content_hash
from ..langgraph_pipeline import process_email as langgraph_process_email, EMAIL_CATEGORIES

LAST_SYNCED_AT_KEY = "last_synced_at"
DUPLICATE_DAYS_WINDOW = 14

APPLICATION_LIKE_CLASSES = {
    "job_application_confirmation",
    "job_rejection",
    "interview_assessment",
    "application_followup",
}


def _extract_linkedin_url(text: str) -> Optional[str]:
    """Extract first LinkedIn profile or company URL from body."""
    if not text:
        return None
    m = re.search(
        r"https?://(?:www\.)?linkedin\.com/(?:in|company)/[\w\-]+/?",
        text,
        re.I,
    )
    return m.group(0).strip()[:500] if m else None


def _is_duplicate_application(
    db: Session,
    company_name: str,
    job_title: Optional[str],
    received: Optional[datetime],
    user_id: Optional[int] = None,
) -> bool:
    """True if same company + similar title within time window (per user)."""
    if not company_name or company_name == "Unknown":
        return False
    window_start = (received or datetime.utcnow()) - timedelta(days=DUPLICATE_DAYS_WINDOW)
    q = db.query(Application).filter(
        Application.company_name == company_name,
        Application.received_date >= window_start,
    )
    if user_id is not None:
        q = q.filter(Application.user_id == user_id)
    if job_title:
        q = q.filter(
            (Application.job_title == job_title) | (Application.position == job_title)
        )
    return q.first() is not None


def _set_transition_timestamps(app: Application, received: Optional[datetime], category: str):
    if not received:
        return
    stage = (app.application_stage or "").strip()
    if stage:
        if stage in ("Applied", "Screening", "Interview", "Offer", "Rejected"):
            app.applied_at = app.applied_at or received
        if stage == "Rejected":
            app.rejected_at = app.rejected_at or received
        elif stage in ("Interview", "Screening"):
            app.interview_at = app.interview_at or received
        elif stage == "Offer":
            app.offer_at = app.offer_at or received
        return

    # Fallback: if stage wasn't set yet, mark applied timestamp.
    app.applied_at = app.applied_at or received


def _parse_received(received_iso: Optional[str]) -> Optional[datetime]:
    if not received_iso:
        return None
    try:
        received = datetime.fromisoformat(received_iso.replace("Z", "+00:00"))
        if received.tzinfo:
            received = received.replace(tzinfo=None)
        return received
    except Exception:
        return None


BATCH_COMMIT_SIZE = 50


def _get_cached_langgraph_state(db: Session, subject: str, sender: str, body: str) -> Optional[dict]:
    """Return cached LangGraph state if present and valid; otherwise None."""
    h = content_hash(subject, sender, body)
    row = db.query(ClassificationCache).filter(ClassificationCache.content_hash == h).first()
    if not row or not row.raw_json:
        return None
    try:
        data = json.loads(row.raw_json)
    except Exception:
        return None
    email_class = (data.get("email_class") or "").strip()
    if email_class not in EMAIL_CATEGORIES:
        return None
    return data


def _persist_langgraph_state_to_cache(
    db: Session, subject: str, sender: str, body: str, state: dict, commit: bool = False
) -> None:
    """Upsert LangGraph state into `classification_cache` by content_hash."""
    h = content_hash(subject, sender, body)
    email_class = (state.get("email_class") or "").strip()
    if email_class not in EMAIL_CATEGORIES:
        email_class = "promotional_marketing"

    raw_json = json.dumps(state)
    existing = db.query(ClassificationCache).filter(ClassificationCache.content_hash == h).first()
    if existing:
        existing.category = email_class
        existing.company_name = state.get("company_name")
        existing.job_title = state.get("job_title")
        existing.confidence = state.get("confidence")
        existing.raw_json = raw_json
    else:
        db.add(
            ClassificationCache(
                content_hash=h,
                category=email_class,
                subcategory=None,
                company_name=state.get("company_name"),
                job_title=state.get("job_title"),
                salary_min=None,
                salary_max=None,
                location=None,
                confidence=state.get("confidence"),
                raw_json=raw_json,
            )
        )
    db.flush()
    if commit:
        db.commit()


def _create_application_and_log(
    db: Session,
    mid: str,
    user_id: Optional[int],
    structured: dict,
    subject: str,
    sender: str,
    body: Optional[str],
    received: Optional[datetime],
    commit: bool = True,
) -> None:
    email_class = (structured.get("email_class") or "").strip()
    if email_class not in EMAIL_CATEGORIES:
        email_class = "promotional_marketing"

    company_name = (structured.get("company_name") or "Unknown")
    company_name = normalize_company_with_db(db, company_name)[:255]

    job_title = structured.get("job_title")
    if job_title:
        job_title = job_title[:255]

    application_stage = (structured.get("application_stage") or "Other")
    requires_action = bool(structured.get("requires_action") or False)
    action_items = structured.get("action_items") or []
    if not isinstance(action_items, list):
        action_items = []

    status = "APPLIED"
    if application_stage == "Rejected":
        status = "REJECTED"
    elif application_stage in ("Interview", "Screening"):
        status = "INTERVIEWING"
    elif application_stage == "Offer":
        status = "OFFER"

    processed_by = structured.get("processed_by")
    if not processed_by:
        model_name = getattr(settings, "openai_model", None) or "gpt-4o-mini"
        processed_by = f"langgraph-openai:{model_name}"

    app = Application(
        gmail_message_id=mid,
        user_id=user_id,
        company_name=company_name,
        position=job_title,
        job_title=job_title,
        status=status,
        category=email_class,
        subcategory=None,
        salary_min=None,
        salary_max=None,
        location=None,
        confidence=structured.get("confidence"),
        email_subject=(subject or "")[:500],
        email_from=(sender or "")[:255],
        email_body=(body or "")[:10000] if body else None,
        received_date=received,
        linkedin_url=_extract_linkedin_url(body or ""),
        classification_reasoning=structured.get("classification_reasoning"),
        position_level=structured.get("position_level"),
        application_stage=application_stage,
        requires_action=requires_action,
        action_items=action_items,
        resume_matched=structured.get("resume_matched"),
        resume_file_id=structured.get("resume_file_id"),
        resume_version=structured.get("resume_version"),
        processing_status=structured.get("processing_status") or "completed",
        processed_by=processed_by,
        needs_review=structured.get("needs_review", False),
    )
    _set_transition_timestamps(app, received, email_class)
    db.add(app)
    db.add(EmailLog(gmail_message_id=mid, user_id=user_id, classification=email_class))
    if commit:
        db.commit()


def _format_date(value: str) -> Optional[str]:
    """Normalize date string to YYYY/MM/DD for Gmail after:/before: queries."""
    value = (value or "").strip()
    if not value:
        return None
    if "/" in value:
        return value
    if "-" in value:
        return value.replace("-", "/")
    return value


def run_sync_with_options(
    db: Session,
    mode: str = "auto",
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    user_id: Optional[int] = None,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> dict:
    """
    Run sync for a user.
    mode=auto: full sync if no last_history_id, then incremental afterwards.
    mode=incremental: history-based delta; falls back to full if historyId missing/too old.
    mode=full: always full sync (all matching emails up to limit).
    after_date: optional YYYY-MM-DD or YYYY/MM/DD; when set, used as full-sync "from" date.
    before_date: optional YYYY-MM-DD or YYYY/MM/DD; when set, used as full-sync "to" date (inclusive).
    Uses classification cache; duplicate detection (company + title + window) per user.
    """
    def progress(processed: int, total: int, message: str):
        set_memory_progress(processed, total, message)
        if on_progress:
            on_progress(processed, total, message)

    # auto: full sync when no historyId or no applications yet (first time); then incremental
    if mode == "auto":
        try:
            has_history = bool(get_last_history_id(db, user_id))
            app_query = db.query(Application)
            if user_id is not None:
                app_query = app_query.filter(Application.user_id == user_id)
            has_apps = app_query.count() > 0
            mode = "incremental" if (has_history and has_apps) else "full"
        except Exception:
            mode = "full"

    progress(0, 0, "Connecting to Gmail…")
    try:
        service = get_gmail_service()
    except FileNotFoundError as e:
        return {"error": str(e), "processed": 0, "created": 0, "skipped": 0, "errors": 0, "full_sync": False}
    except Exception as e:
        return {"error": str(e), "processed": 0, "created": 0, "skipped": 0, "errors": 0, "full_sync": False}

    all_emails = []
    new_history_id = None
    full_sync = False

    if mode == "incremental":
        last_id = get_last_history_id(db, user_id)
        if last_id:
            def hist_progress(n: int, msg: str):
                progress(n, 0, msg)
            emails, new_history_id, history_too_old = fetch_emails_from_history(
                service, last_id, on_progress=hist_progress
            )
            if history_too_old:
                full_sync = True
                # fall through to full sync
            else:
                all_emails = emails
        else:
            full_sync = True

    if mode == "full" or full_sync or not all_emails:
        if full_sync or mode == "full":
            def _default_after_date() -> str:
                days_back = max(1, settings.gmail_full_sync_days_back or 90)
                return (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")

            after_date_val = None
            if after_date:
                after_date_val = _format_date(after_date)
            if not after_date_val and settings.gmail_full_sync_after_date:
                after_date_val = _format_date(settings.gmail_full_sync_after_date)
            if not after_date_val and not settings.gmail_full_sync_ignore_last_synced:
                # Per-user: use SyncState last_full_sync_at / last_synced_at; else global SyncMetadata
                if user_id is not None:
                    sync_row = get_sync_state(db, user_id)
                    if sync_row:
                        ts = sync_row.last_full_sync_at or sync_row.last_synced_at
                        if ts:
                            after_date_val = ts.strftime("%Y/%m/%d")
                if not after_date_val:
                    row = db.query(SyncMetadata).filter(SyncMetadata.key == LAST_SYNCED_AT_KEY).first()
                    if row and row.value:
                        try:
                            last_synced = datetime.fromisoformat(row.value.replace("Z", "+00:00"))
                            if last_synced.tzinfo:
                                last_synced = last_synced.replace(tzinfo=None)
                            after_date_val = last_synced.strftime("%Y/%m/%d")
                        except Exception:
                            after_date_val = None
            if not after_date_val:
                after_date_val = _default_after_date()

            before_date_val = _format_date(before_date) if before_date else None
            date_prefix = f"after:{after_date_val}"
            if before_date_val:
                date_prefix += f" before:{before_date_val}"

            logger.info(f"=== FULL SYNC DEBUG ===")
            logger.info(f"Searching emails after: {after_date_val}" + (f" before: {before_date_val}" if before_date_val else ""))
            logger.info(f"Max results per query: {settings.gmail_full_sync_max_per_query}")

            queries = [
                # Subject-based searches
                f"{date_prefix} subject:(application OR applied OR interview OR assessment OR position OR opportunity OR hiring OR job)",
                f"{date_prefix} subject:(offer OR rejection OR rejected OR regret OR unfortunately OR congratulations)",
                f"{date_prefix} subject:(\"thank you for applying\" OR \"thank you for your interest\" OR \"next steps\" OR \"move forward\")",
                # From-based searches
                f"{date_prefix} from:(noreply OR no-reply OR careers OR recruiting OR talent OR jobs OR hr OR hire OR greenhouse OR lever OR workday)",
                f"{date_prefix} from:(linkedin.com OR indeed.com OR glassdoor.com OR ziprecruiter.com OR monster.com)",
                # Job board and ATS platforms
                f"{date_prefix} (from:myworkdayjobs.com OR from:greenhouse.io OR from:lever.co OR from:jobvite.com OR from:icims.com)",
                # Common job-related phrases
                f"{date_prefix} (\"application received\" OR \"application status\" OR \"interview invitation\" OR \"phone screen\" OR \"technical interview\")",
            ]

            logger.info(f"Running {len(queries)} Gmail queries...")
            seen_ids = set()
            fetch_error = None
            for idx, q in enumerate(queries, 1):
                try:
                    logger.info(f"Query {idx}/{len(queries)}: running...")
                    emails = fetch_emails(service, q, max_results=settings.gmail_full_sync_max_per_query)
                    logger.info(f"  → Found {len(emails)} emails")
                    new_emails = 0
                    for e in emails:
                        if e.get("id") and e["id"] not in seen_ids:
                            seen_ids.add(e["id"])
                            all_emails.append(e)
                            new_emails += 1
                    logger.info(f"  → {new_emails} unique emails (total unique so far: {len(all_emails)})")
                except Exception as e:
                    fetch_error = str(e)
                    logger.error(f"  → Query failed: {fetch_error}")
                    if not all_emails:
                        return {"error": f"Gmail fetch failed: {fetch_error}", "processed": 0, "created": 0, "skipped": 0, "errors": 0, "full_sync": True}
            if not new_history_id:
                new_history_id = get_profile_history_id(service)
            full_sync = True

    total = len(all_emails)
    logger.info(f"=== PROCESSING {total} EMAILS ===")
    progress(0, total, "Classifying…")

    created = 0
    skipped = 0
    errors = 0
    skipped_existing = 0
    skipped_duplicate = 0
    pending_commits = 0

    # Phase 1: parse, check existing, check cache; collect pending (cache misses) for LangGraph
    PendingItem = Tuple[int, str, str, str, str, str]  # (idx, mid, subject, sender, body, received_iso)
    pending: List[PendingItem] = []
    processed_after_phase1 = 0

    for i, email in enumerate(all_emails):
        try:
            mid, subject, sender, body, received_iso = email_to_parts(email)
        except Exception as e:
            logger.error(f"Email {i+1}/{total}: Failed to parse - {str(e)}")
            db.add(EmailLog(gmail_message_id=email.get("id", ""), user_id=user_id, error=str(e)))
            db.commit()
            errors += 1
            progress(i + 1, total, "Classifying…")
            continue

        existing_q = db.query(Application).filter(Application.gmail_message_id == mid)
        if user_id is not None:
            existing_q = existing_q.filter(Application.user_id == user_id)
        if existing_q.first():
            logger.debug(f"Email {i+1}/{total}: Already exists (msg_id={mid})")
            skipped += 1
            skipped_existing += 1
            progress(i + 1, total, "Classifying…")
            continue

        cached = _get_cached_langgraph_state(db, subject, sender, body)
        if cached is not None:
            received = _parse_received(received_iso)
            email_class = cached.get("email_class")
            company_name = cached.get("company_name") or "Unknown"
            job_title = cached.get("job_title")
            if email_class in APPLICATION_LIKE_CLASSES and _is_duplicate_application(db, company_name, job_title, received, user_id):
                logger.info(f"Email {i+1}/{total}: DUPLICATE (msg_id={mid})")
                skipped += 1
                skipped_duplicate += 1
            else:
                _create_application_and_log(
                    db, mid, user_id, cached, subject, sender, body, received, commit=False
                )
                created += 1
                pending_commits += 1
                if pending_commits >= BATCH_COMMIT_SIZE:
                    db.commit()
                    pending_commits = 0
            progress(i + 1, total, "Classifying…")
            continue

        pending.append((i, mid, subject, sender, body, received_iso))

    # Phase 2: parallel LangGraph for pending (per-email)
    llm_results: dict[int, Tuple[Optional[dict], Optional[Exception]]] = {}
    max_concurrency = max(1, getattr(settings, "classification_max_concurrency", 5))

    def _run_langgraph(item: PendingItem) -> Tuple[int, Optional[dict], Optional[Exception]]:
        idx, mid, subject, sender, body, received_iso = item
        try:
            result = langgraph_process_email(
                email_id=mid,
                subject=subject,
                body=body,
                sender=sender,
                received_date=received_iso or "",
            )
            return (idx, result, None)
        except Exception as e:
            return (idx, None, e)

    if pending:
        progress(total - len(pending), total, "Classifying…")
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures = {executor.submit(_run_langgraph, item): item for item in pending}
            for fut in as_completed(futures):
                idx, result, err = fut.result()
                llm_results[idx] = (result, err)

    # Phase 3: persist cache, duplicate check, create applications (main thread, same DB session)
    processed_so_far = total - len(pending)
    for item in sorted(pending, key=lambda x: x[0]):
        idx, mid, subject, sender, body, received_iso = item
        result, err = llm_results.get(idx, (None, None))
        processed_so_far += 1
        progress(processed_so_far, total, "Classifying…")

        if err is not None:
            logger.error(f"Email {idx+1}/{total}: Classification failed - {str(err)[:100]}")
            db.add(EmailLog(gmail_message_id=mid, user_id=user_id, error=str(err), classification=None))
            db.commit()
            errors += 1
            continue

        try:
            structured = dict(result or {})
            _persist_langgraph_state_to_cache(db, subject, sender, body, structured, commit=False)
        except Exception as e:
            logger.error(f"Email {idx+1}/{total}: Cache persist failed - {str(e)[:100]}")
            db.add(EmailLog(gmail_message_id=mid, user_id=user_id, error=str(e), classification=None))
            db.commit()
            errors += 1
            continue

        received = _parse_received(received_iso)
        email_class = structured.get("email_class")
        company_name = structured.get("company_name") or "Unknown"
        job_title = structured.get("job_title")
        if email_class in APPLICATION_LIKE_CLASSES and _is_duplicate_application(db, company_name, job_title, received, user_id):
            logger.info(f"Email {idx+1}/{total}: DUPLICATE (msg_id={mid})")
            skipped += 1
            skipped_duplicate += 1
            continue

        logger.info(f"Email {idx+1}/{total}: CREATING (msg_id={mid}, class={email_class})")
        _create_application_and_log(db, mid, user_id, structured, subject, sender, body, received, commit=False)
        created += 1
        pending_commits += 1
        if pending_commits >= BATCH_COMMIT_SIZE:
            db.commit()
            pending_commits = 0

    if pending_commits > 0:
        db.commit()

    now = datetime.utcnow()
    if new_history_id:
        set_last_history_id(db, new_history_id, user_id)
    if full_sync and user_id is not None:
        set_last_full_sync_at(db, user_id)
    row = db.query(SyncMetadata).filter(SyncMetadata.key == LAST_SYNCED_AT_KEY).first()
    if row:
        row.value = now.isoformat()
        row.updated_at = now
    else:
        db.add(SyncMetadata(key=LAST_SYNCED_AT_KEY, value=now.isoformat()))
    db.commit()

    logger.info(f"=== SYNC COMPLETE ===")
    logger.info(f"Total emails processed: {total}")
    logger.info(f"Created: {created}")
    logger.info(f"Skipped (already exists): {skipped_existing}")
    logger.info(f"Skipped (duplicate): {skipped_duplicate}")
    logger.info(f"Errors: {errors}")
    logger.info(f"Full sync: {full_sync}")

    return {
        "processed": total,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "full_sync": full_sync,
    }


def run_sync(db: Session, on_progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """Legacy: full sync. Kept for backward compatibility."""
    return run_sync_with_options(db, mode="full", on_progress=on_progress)
