#!/usr/bin/env python3
"""
Reclassify applications in the database using batch LLM calls.

Fetches applications that have email_subject/email_from/email_body, re-runs
classification in batches (one API call per N emails), updates Application
records and the classification cache.

Usage (from backend directory; use the project venv so app deps are available):
  .venv/bin/python scripts/reclassify_emails.py [options]
  # Or: PYTHONPATH=. .venv/bin/python scripts/reclassify_emails.py [options]

Options:
  --user-id ID       Only reclassify applications for this user (default: all)
  --user-email EMAIL Only reclassify for user with this email (looks up user_id)
  --limit N          Maximum number of applications to process (default: no limit)
  --batch-size N     Emails per LLM call (default: 10)
  --dry-run          Fetch and classify but do not write to DB
  --verbose, -v      Log each application reclassification (id, old -> new category)
  --quiet, -q        Only print final summary (no per-batch progress)
"""
import argparse
import os
import sys
from datetime import datetime

# Ensure backend app is importable when run as script from backend or project root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.dirname(_script_dir)
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Application, ClassificationCache, User
from app.email_classifier import content_hash, structured_classify_emails_batch
from app.services.classification_service import (
    normalize_company_with_db,
    persist_llm_result_to_cache,
)


def _set_transition_timestamps(app: Application, received: datetime | None, category: str) -> None:
    if not received:
        return
    app.applied_at = app.applied_at or received
    if category == "REJECTION":
        app.rejected_at = app.rejected_at or received
    elif category in ("INTERVIEW_REQUEST", "SCREENING_REQUEST", "ASSESSMENT"):
        app.interview_at = app.interview_at or received
    elif category == "OFFER":
        app.offer_at = app.offer_at or received


def _apply_result_to_application(app: Application, result: dict, company_normalized: str) -> None:
    app.category = result.get("category") or "OTHER"
    app.subcategory = result.get("subcategory")
    app.company_name = company_normalized
    app.job_title = (result.get("job_title") or "")[:255] or None
    app.salary_min = result.get("salary_min")
    app.salary_max = result.get("salary_max")
    app.location = (result.get("location") or "")[:255] or None
    app.confidence = result.get("confidence")
    _set_transition_timestamps(app, app.received_date, app.category)


def reclassify(
    db: Session,
    *,
    user_id: int | None = None,
    limit: int | None = None,
    batch_size: int = 10,
    dry_run: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> tuple[int, int, int]:
    """
    Reclassify applications. Returns (processed, updated, errors).
    """
    q = (
        db.query(Application)
        .filter(
            Application.email_subject.isnot(None),
            Application.email_from.isnot(None),
        )
        .order_by(Application.id.asc())
    )
    if user_id is not None:
        q = q.filter(Application.user_id == user_id)
    if limit is not None:
        q = q.limit(limit)
    applications = q.all()

    if not applications:
        return 0, 0, 0

    processed = 0
    updated = 0
    errors = 0
    batch: list[Application] = []

    def flush_batch() -> None:
        nonlocal processed, updated, errors
        if not batch:
            return
        emails = [
            (
                (a.email_subject or "").strip(),
                (a.email_body or "")[:5000],
                (a.email_from or "").strip(),
            )
            for a in batch
        ]
        try:
            results = structured_classify_emails_batch(emails)
        except Exception as e:
            print(f"  Batch LLM error: {e}", file=sys.stderr)
            errors += len(batch)
            batch.clear()
            return

        if len(results) != len(batch):
            print(f"  Batch result length mismatch: got {len(results)}, expected {len(batch)}", file=sys.stderr)
            errors += len(batch)
            batch.clear()
            return

        for app, result in zip(batch, results):
            processed += 1
            subject = app.email_subject or ""
            sender = app.email_from or ""
            body = app.email_body or ""
            company_normalized = normalize_company_with_db(db, result.get("company_name") or "Unknown")
            result["company_name"] = company_normalized
            new_cat = result.get("category") or "OTHER"
            if verbose:
                print(f"  app {app.id}: {app.category or 'OTHER'} -> {new_cat}  ({app.company_name})", flush=True)

            if dry_run:
                updated += 1
                continue

            # Remove old cache row so we can re-insert with new classification
            h = content_hash(subject, sender, body)
            db.query(ClassificationCache).filter(ClassificationCache.content_hash == h).delete(synchronize_session=False)

            _apply_result_to_application(app, result, company_normalized)
            updated += 1

            # Persist new result to cache (same content_hash, new category/etc.)
            persist_llm_result_to_cache(db, subject, sender, body, result, commit=False)

        if not dry_run:
            db.commit()
        batch.clear()

    for app in applications:
        batch.append(app)
        if len(batch) >= batch_size:
            flush_batch()
            print(f"  Progress: {processed} processed, {updated} updated, {errors} errors", flush=True)

    if batch:
        flush_batch()
        print(f"  Progress: {processed} processed, {updated} updated, {errors} errors", flush=True)

    return processed, updated, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reclassify applications in the database using batch LLM calls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--user-id", type=int, default=None, help="Only reclassify for this user ID")
    parser.add_argument("--user-email", type=str, default=None, help="Only reclassify for user with this email")
    parser.add_argument("--limit", type=int, default=None, help="Max applications to process")
    parser.add_argument("--batch-size", type=int, default=10, help="Emails per LLM call (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    parser.add_argument("--verbose", "-v", action="store_true", help="Log each app reclassification (id, old -> new category)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print final summary (no per-batch progress)")
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 20:
        print("--batch-size must be between 1 and 20", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user_id = args.user_id
        if args.user_email is not None:
            user = db.query(User).filter(User.email == args.user_email.strip()).first()
            if not user:
                print(f"User not found: {args.user_email}", file=sys.stderr)
                return 1
            user_id = user.id
            print(f"Resolved --user-email to user_id={user_id}")

        print(f"Reclassify: user_id={user_id}, limit={args.limit}, batch_size={args.batch_size}, dry_run={args.dry_run}")
        processed, updated, errors = reclassify(
            db,
            user_id=user_id,
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            verbose=args.verbose,
            quiet=args.quiet,
        )
        print(f"Done: {processed} processed, {updated} updated, {errors} errors")
        return 0 if errors == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
