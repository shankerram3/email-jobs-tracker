"""Background email sync: history-based incremental, classification cache, duplicate detection."""
import re
import logging
from datetime import datetime, timedelta
from typing import Callable, Optional
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
from ..models import Application, EmailLog, SyncMetadata, SyncState
from ..sync_state_db import (
    get_sync_state,
    get_last_history_id,
    set_last_history_id,
    set_memory_progress,
)
from .classification_service import classify_and_cache

LAST_SYNCED_AT_KEY = "last_synced_at"
DUPLICATE_DAYS_WINDOW = 14


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
    app.applied_at = app.applied_at or received
    if category == "REJECTION":
        app.rejected_at = app.rejected_at or received
    elif category in ("INTERVIEW_REQUEST", "ASSESSMENT"):
        app.interview_at = app.interview_at or received
    elif category == "OFFER":
        app.offer_at = app.offer_at or received


def run_sync_with_options(
    db: Session,
    mode: str = "auto",
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    user_id: Optional[int] = None,
) -> dict:
    """
    Run sync for a user.
    mode=auto: full sync if no last_history_id, then incremental afterwards.
    mode=incremental: history-based delta; falls back to full if historyId missing/too old.
    mode=full: always full sync (all matching emails up to limit).
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
            def _format_after_date(value: str) -> Optional[str]:
                value = value.strip()
                if not value:
                    return None
                if "/" in value:
                    return value
                if "-" in value:
                    return value.replace("-", "/")
                return None

            def _default_after_date() -> str:
                days_back = max(1, settings.gmail_full_sync_days_back or 90)
                return (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y/%m/%d")

            after_date = None
            if settings.gmail_full_sync_after_date:
                after_date = _format_after_date(settings.gmail_full_sync_after_date)
            if not after_date and not settings.gmail_full_sync_ignore_last_synced:
                row = db.query(SyncMetadata).filter(SyncMetadata.key == LAST_SYNCED_AT_KEY).first()
                if row and row.value:
                    try:
                        last_synced = datetime.fromisoformat(row.value.replace("Z", "+00:00"))
                        if last_synced.tzinfo:
                            last_synced = last_synced.replace(tzinfo=None)
                        after_date = last_synced.strftime("%Y/%m/%d")
                    except Exception:
                        after_date = None
            if not after_date:
                after_date = _default_after_date()

            logger.info(f"=== FULL SYNC DEBUG ===")
            logger.info(f"Searching emails after: {after_date}")
            logger.info(f"Max results per query: {settings.gmail_full_sync_max_per_query}")

            queries = [
                # Subject-based searches
                f"after:{after_date} subject:(application OR applied OR interview OR assessment OR position OR opportunity OR hiring OR job)",
                f"after:{after_date} subject:(offer OR rejection OR rejected OR regret OR unfortunately OR congratulations)",
                f"after:{after_date} subject:(\"thank you for applying\" OR \"thank you for your interest\" OR \"next steps\" OR \"move forward\")",
                # From-based searches
                f"after:{after_date} from:(noreply OR no-reply OR careers OR recruiting OR talent OR jobs OR hr OR hire OR greenhouse OR lever OR workday)",
                f"after:{after_date} from:(linkedin.com OR indeed.com OR glassdoor.com OR ziprecruiter.com OR monster.com)",
                # Job board and ATS platforms
                f"after:{after_date} (from:myworkdayjobs.com OR from:greenhouse.io OR from:lever.co OR from:jobvite.com OR from:icims.com)",
                # Common job-related phrases
                f"after:{after_date} (\"application received\" OR \"application status\" OR \"interview invitation\" OR \"phone screen\" OR \"technical interview\")",
            ]

            logger.info(f"Running {len(queries)} Gmail queries...")
            seen_ids = set()
            fetch_error = None
            for idx, q in enumerate(queries, 1):
                try:
                    logger.info(f"Query {idx}/{len(queries)}: {q[:100]}...")
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

    for i, email in enumerate(all_emails):
        try:
            mid, subject, sender, body, received_iso = email_to_parts(email)
        except Exception as e:
            logger.error(f"Email {i+1}/{total}: Failed to parse - {str(e)}")
            db.add(EmailLog(gmail_message_id=email.get("id", ""), error=str(e)))
            db.commit()
            errors += 1
            progress(i + 1, total, "Classifying…")
            continue

        existing = db.query(Application).filter(Application.gmail_message_id == mid).first()
        if existing:
            logger.debug(f"Email {i+1}/{total}: Already exists - {subject[:50]}")
            skipped += 1
            skipped_existing += 1
            progress(i + 1, total, "Classifying…")
            continue

        try:
            structured = classify_and_cache(db, subject, body, sender)
        except Exception as e:
            logger.error(f"Email {i+1}/{total}: Classification failed - {str(e)[:100]}")
            db.add(EmailLog(gmail_message_id=mid, error=str(e), classification=None))
            db.commit()
            errors += 1
            progress(i + 1, total, "Classifying…")
            continue

        received = None
        if received_iso:
            try:
                received = datetime.fromisoformat(received_iso.replace("Z", "+00:00"))
                if received.tzinfo:
                    received = received.replace(tzinfo=None)
            except Exception:
                pass

        company = structured.get("company_name") or "Unknown"
        job_title = structured.get("job_title")
        if _is_duplicate_application(db, company, job_title, received, user_id):
            logger.info(f"Email {i+1}/{total}: DUPLICATE - {company} / {job_title} - {subject[:50]}")
            skipped += 1
            skipped_duplicate += 1
            progress(i + 1, total, "Classifying…")
            continue

        category = structured.get("category") or "OTHER"
        logger.info(f"Email {i+1}/{total}: CREATING - {company} / {job_title} / {category} - {subject[:50]}")

        app = Application(
            gmail_message_id=mid,
            company_name=company[:255],
            position=job_title[:255] if job_title else None,
            job_title=job_title[:255] if job_title else None,
            status="APPLIED",
            category=category,
            subcategory=structured.get("subcategory"),
            salary_min=structured.get("salary_min"),
            salary_max=structured.get("salary_max"),
            location=structured.get("location"),
            confidence=structured.get("confidence"),
            email_subject=(subject or "")[:500],
            email_from=(sender or "")[:255],
            email_body=(body or "")[:10000] if body else None,
            received_date=received,
            linkedin_url=_extract_linkedin_url(body or ""),
        )
        _set_transition_timestamps(app, received, category)
        db.add(app)
        db.add(EmailLog(gmail_message_id=mid, classification=category))
        db.commit()
        created += 1
        progress(i + 1, total, "Classifying…")

    now = datetime.utcnow()
    if new_history_id:
        set_last_history_id(db, new_history_id, user_id)
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
