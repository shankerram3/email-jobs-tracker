"""Batch reprocessing pipeline for existing Application rows.

Goal: re-run LangGraph classify+extract over saved email content and update DB fields.
Designed to run in a background worker (Celery), with DB-backed progress updates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application
from ..langgraph_pipeline import process_emails_batch as langgraph_process_batch
from .classification_service import normalize_company_with_db
from .email_processor import _persist_langgraph_state_to_cache  # keep cache consistent


ProgressCb = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ReprocessOptions:
    only_needs_review: bool = True
    min_confidence: Optional[float] = None
    after_date: Optional[datetime] = None
    before_date: Optional[datetime] = None
    limit: int = 500
    batch_size: int = 25
    dry_run: bool = False


def _status_from_stage(stage: str) -> str:
    stage = (stage or "").strip()
    if stage == "Rejected":
        return "REJECTED"
    if stage in ("Interview", "Screening"):
        return "INTERVIEWING"
    if stage == "Offer":
        return "OFFER"
    return "APPLIED"


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    # Accept YYYY-MM-DD or ISO.
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def run_reprocess_applications(
    db: Session,
    *,
    user_id: int,
    options: ReprocessOptions,
    on_progress: Optional[ProgressCb] = None,
) -> dict:
    """
    Reprocess existing Application rows for a user.

    Uses LangGraph batch processing (which can internally fall back to per-email
    processing for low-confidence critical categories).
    """
    def progress(p: int, t: int, msg: str) -> None:
        if on_progress:
            on_progress(p, t, msg)

    q = db.query(Application).filter(Application.user_id == user_id)

    # Only reprocess rows that likely correspond to actual applications.
    q = q.filter(Application.gmail_message_id.isnot(None))

    if options.only_needs_review:
        q = q.filter(Application.needs_review == True)  # noqa: E712

    if options.min_confidence is not None:
        q = q.filter(Application.confidence.isnot(None)).filter(Application.confidence < float(options.min_confidence))

    if options.after_date is not None:
        q = q.filter(Application.received_date.isnot(None)).filter(Application.received_date >= options.after_date)
    if options.before_date is not None:
        q = q.filter(Application.received_date.isnot(None)).filter(Application.received_date <= options.before_date)

    q = q.order_by(Application.received_date.desc().nulls_last(), Application.id.desc())

    limit = max(1, int(options.limit or 500))
    apps = q.limit(limit).all()

    total = len(apps)
    if total == 0:
        return {"total": 0, "processed": 0, "updated": 0, "skipped": 0, "errors": 0}

    progress(0, total, "Reprocessing…")

    updated = 0
    skipped = 0
    errors = 0

    batch_size = max(1, int(options.batch_size or 25))
    model_name = getattr(settings, "openai_model", None) or "gpt-4o-mini"
    processed_by = f"langgraph-openai:{model_name}-reprocess"

    for i in range(0, total, batch_size):
        batch_apps = apps[i : i + batch_size]

        payload = []
        for app in batch_apps:
            payload.append(
                {
                    "email_id": app.gmail_message_id,
                    "subject": app.email_subject or "",
                    "body": app.email_body or "",
                    "sender": app.email_from or "",
                    "received_date": app.received_date.isoformat() if app.received_date else "",
                }
            )

        try:
            results = langgraph_process_batch(payload, batch_size=min(10, len(payload)))
        except Exception:
            results = []

        if not results or len(results) != len(batch_apps):
            # Fallback: process_batch already falls back internally for some cases,
            # but if the batch call itself failed, treat as errors.
            errors += len(batch_apps)
            progress(min(i + len(batch_apps), total), total, "Reprocessing…")
            continue

        for app, r in zip(batch_apps, results):
            # Defensive: r is EmailState dict-like
            try:
                r = dict(r or {})
            except Exception:
                errors += 1
                continue

            email_class = (r.get("email_class") or "").strip()
            company_name = (r.get("company_name") or "").strip() or None
            job_title = (r.get("job_title") or "").strip() or None

            # Normalize company for consistency with ingestion pipeline.
            if company_name:
                company_name = normalize_company_with_db(db, company_name)[:255]

            stage = (r.get("application_stage") or app.application_stage or "Other")
            status = _status_from_stage(stage)

            # Update cache for future ingestion dedupe/classification speedups.
            try:
                _persist_langgraph_state_to_cache(
                    db,
                    app.email_subject or "",
                    app.email_from or "",
                    app.email_body or "",
                    r,
                    user_id,
                    commit=False,
                )
            except Exception:
                # Best-effort; cache should not block DB updates.
                pass

            if options.dry_run:
                skipped += 1
                continue

            # Only overwrite with non-empty values to avoid losing existing data.
            if email_class:
                app.category = email_class
            if company_name:
                app.company_name = company_name
            if job_title:
                app.job_title = job_title[:255]
                app.position = job_title[:255]

            app.confidence = r.get("confidence")
            app.classification_reasoning = r.get("classification_reasoning")
            app.position_level = r.get("position_level")
            app.application_stage = stage
            app.requires_action = bool(r.get("requires_action") or False)
            app.action_items = r.get("action_items") or []
            app.processing_status = r.get("processing_status") or "completed"
            app.processed_by = processed_by
            app.needs_review = bool(r.get("needs_review") or False)
            app.status = status

            updated += 1

        db.commit()
        progress(min(i + len(batch_apps), total), total, "Reprocessing…")

    return {
        "total": total,
        "processed": total,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
