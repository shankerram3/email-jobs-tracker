"""Background email sync and classification."""
from datetime import datetime, timedelta
from typing import Callable, Optional
from sqlalchemy.orm import Session

from ..gmail_service import get_gmail_service, fetch_emails, email_to_parts
from ..email_classifier import classify_email, extract_company_name
from ..models import Application, EmailLog


def run_sync(db: Session, on_progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """
    Fetch job-related emails from Gmail, classify with AI, and upsert into DB.
    Returns counts: processed, created, skipped, errors.
    on_progress(processed, total, message) is called to report progress.
    """
    if on_progress:
        on_progress(0, 0, "Connecting to Gmail…")
    try:
        service = get_gmail_service()
    except FileNotFoundError as e:
        return {"error": str(e), "processed": 0, "created": 0, "skipped": 0, "errors": 0}
    except Exception as e:
        return {"error": str(e), "processed": 0, "created": 0, "skipped": 0, "errors": 0}

    after_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y/%m/%d")
    queries = [
        f"after:{after_date} subject:(application OR interview OR assessment OR position)",
        f"after:{after_date} from:(noreply OR no-reply OR careers OR recruiting OR talent)",
    ]
    all_emails = []
    seen_ids = set()
    for q in queries:
        try:
            emails = fetch_emails(service, q, max_results=50)
            for e in emails:
                if e.get("id") and e["id"] not in seen_ids:
                    seen_ids.add(e["id"])
                    all_emails.append(e)
        except Exception:
            continue

    total = len(all_emails)
    if on_progress:
        on_progress(0, total, "Classifying…")

    created = 0
    skipped = 0
    errors = 0

    for i, email in enumerate(all_emails):
        try:
            mid, subject, sender, body, received_iso = email_to_parts(email)
        except Exception as e:
            log = EmailLog(gmail_message_id=email.get("id", ""), error=str(e))
            db.add(log)
            db.commit()
            errors += 1
            if on_progress:
                on_progress(i + 1, total, "Classifying…")
            continue

        existing = db.query(Application).filter(Application.gmail_message_id == mid).first()
        if existing:
            skipped += 1
            if on_progress:
                on_progress(i + 1, total, "Classifying…")
            continue

        try:
            category = classify_email(subject, body, sender)
            company = extract_company_name(subject, body, sender)
        except Exception as e:
            log = EmailLog(gmail_message_id=mid, error=str(e), classification=None)
            db.add(log)
            db.commit()
            errors += 1
            if on_progress:
                on_progress(i + 1, total, "Classifying…")
            continue

        received = None
        if received_iso:
            try:
                received = datetime.fromisoformat(received_iso.replace("Z", "+00:00"))
                if received.tzinfo:
                    received = received.replace(tzinfo=None)
            except Exception:
                pass

        app = Application(
            gmail_message_id=mid,
            company_name=company[:255] if company else "Unknown",
            position=None,
            status="APPLIED",
            category=category,
            email_subject=(subject or "")[:500],
            email_from=(sender or "")[:255],
            email_body=(body or "")[:10000] if body else None,
            received_date=received,
        )
        db.add(app)
        log = EmailLog(gmail_message_id=mid, classification=category)
        db.add(log)
        db.commit()
        created += 1
        if on_progress:
            on_progress(i + 1, total, "Classifying…")

    return {
        "processed": len(all_emails),
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }
