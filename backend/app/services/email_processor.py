"""Background email sync: history-based incremental, classification cache, duplicate detection."""
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
from ..models import Application, EmailLog, SyncMetadata, SyncState
from ..sync_state_db import (
    get_sync_state,
    get_last_history_id,
    set_last_history_id,
    set_last_full_sync_at,
    set_memory_progress,
)
from .classification_service import (
    classify_and_cache,
    get_cached_classification,
    persist_llm_result_to_cache,
    normalize_company_with_db,
)
from ..email_classifier import classify_email_llm_only, structured_classify_emails_batch

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


def _create_application_and_log(
    db: Session,
    mid: str,
    user_id: Optional[int],
    structured: dict,
    subject: str,
    sender: str,
    body: Optional[str],
    received: Optional[datetime],
) -> None:
    category = structured.get("category") or "OTHER"
    job_title = structured.get("job_title")
    company_name = (structured.get("company_name") or "Unknown")[:255]
    app = Application(
        gmail_message_id=mid,
        user_id=user_id,
        company_name=company_name,
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
    db.add(EmailLog(gmail_message_id=mid, user_id=user_id, classification=category))
    db.commit()


def _format_after_date(value: str) -> Optional[str]:
    """Normalize date string to YYYY/MM/DD for Gmail after: query."""
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
) -> dict:
    """
    Run sync for a user.
    mode=auto: full sync if no last_history_id, then incremental afterwards.
    mode=incremental: history-based delta; falls back to full if historyId missing/too old.
    mode=full: always full sync (all matching emails up to limit).
    after_date: optional YYYY-MM-DD or YYYY/MM/DD; when set, used as full-sync "from" date.
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
                after_date_val = _format_after_date(after_date)
            if not after_date_val and settings.gmail_full_sync_after_date:
                after_date_val = _format_after_date(settings.gmail_full_sync_after_date)
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

            logger.info(f"=== FULL SYNC DEBUG ===")
            logger.info(f"Searching emails after: {after_date_val}")
            logger.info(f"Max results per query: {settings.gmail_full_sync_max_per_query}")

            queries = [
                # Subject-based searches
                f"after:{after_date_val} subject:(application OR applied OR interview OR assessment OR position OR opportunity OR hiring OR job)",
                f"after:{after_date_val} subject:(offer OR rejection OR rejected OR regret OR unfortunately OR congratulations)",
                f"after:{after_date_val} subject:(\"thank you for applying\" OR \"thank you for your interest\" OR \"next steps\" OR \"move forward\")",
                # From-based searches
                f"after:{after_date_val} from:(noreply OR no-reply OR careers OR recruiting OR talent OR jobs OR hr OR hire OR greenhouse OR lever OR workday)",
                f"after:{after_date_val} from:(linkedin.com OR indeed.com OR glassdoor.com OR ziprecruiter.com OR monster.com)",
                # Job board and ATS platforms
                f"after:{after_date_val} (from:myworkdayjobs.com OR from:greenhouse.io OR from:lever.co OR from:jobvite.com OR from:icims.com)",
                # Common job-related phrases
                f"after:{after_date_val} (\"application received\" OR \"application status\" OR \"interview invitation\" OR \"phone screen\" OR \"technical interview\")",
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

    # Phase 1: parse, check existing, check cache; collect pending (cache misses) for LLM
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

        cached = get_cached_classification(db, subject, sender, body)
        if cached is not None:
            company = normalize_company_with_db(db, cached["company_name"])
            cached = {**cached, "company_name": company}
            received = _parse_received(received_iso)
            company_name = cached.get("company_name") or "Unknown"
            job_title = cached.get("job_title")
            if _is_duplicate_application(db, company_name, job_title, received, user_id):
                logger.info(f"Email {i+1}/{total}: DUPLICATE (msg_id={mid})")
                skipped += 1
                skipped_duplicate += 1
            else:
                _create_application_and_log(
                    db, mid, user_id, cached, subject, sender, body, received
                )
                created += 1
            progress(i + 1, total, "Classifying…")
            continue

        pending.append((i, mid, subject, sender, body, received_iso))

    # Phase 2: parallel LLM for pending (batch or per-email)
    llm_results: dict[int, Tuple[Optional[dict], Optional[Exception]]] = {}
    max_concurrency = max(1, getattr(settings, "classification_max_concurrency", 5))
    use_batch = getattr(settings, "classification_use_batch_prompt", False) and getattr(settings, "classification_batch_size", 0) > 0
    batch_size = getattr(settings, "classification_batch_size", 0) if use_batch else 0

    def _run_llm(item: PendingItem) -> Tuple[int, Optional[dict], Optional[Exception]]:
        idx, mid, subject, sender, body, _ = item
        try:
            result = classify_email_llm_only(subject, body, sender)
            return (idx, result, None)
        except Exception as e:
            return (idx, None, e)

    def _run_batch(chunk: List[PendingItem]) -> List[Tuple[int, Optional[dict], Optional[Exception]]]:
        emails = [(item[2], item[4], item[3]) for item in chunk]  # subject, body, sender
        batch_results = structured_classify_emails_batch(emails)
        if not batch_results or len(batch_results) != len(chunk):
            return [_run_llm(item) for item in chunk]
        return [(chunk[i][0], batch_results[i], None) for i in range(len(chunk))]

    if pending:
        progress(total - len(pending), total, "Classifying…")
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            if use_batch and batch_size > 0:
                chunks = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
                futures = [executor.submit(_run_batch, c) for c in chunks]
                for fut in as_completed(futures):
                    for idx, result, err in fut.result():
                        llm_results[idx] = (result, err)
            else:
                futures = {executor.submit(_run_llm, item): item for item in pending}
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
            structured = persist_llm_result_to_cache(db, subject, sender, body, result)
        except Exception as e:
            logger.error(f"Email {idx+1}/{total}: Cache persist failed - {str(e)[:100]}")
            db.add(EmailLog(gmail_message_id=mid, user_id=user_id, error=str(e), classification=None))
            db.commit()
            errors += 1
            continue

        received = _parse_received(received_iso)
        company_name = structured.get("company_name") or "Unknown"
        job_title = structured.get("job_title")
        if _is_duplicate_application(db, company_name, job_title, received, user_id):
            logger.info(f"Email {idx+1}/{total}: DUPLICATE (msg_id={mid})")
            skipped += 1
            skipped_duplicate += 1
            continue

        category = structured.get("category") or "OTHER"
        logger.info(f"Email {idx+1}/{total}: CREATING (msg_id={mid}, category={category})")
        _create_application_and_log(db, mid, user_id, structured, subject, sender, body, received)
        created += 1

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
