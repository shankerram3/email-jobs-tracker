#!/usr/bin/env python3
"""
Reprocess existing applications in the DB using the LangGraph pipeline.

This is the "just run it" option (no Redis/Celery, no auth tokens).

Usage (from backend/; use the project venv):
  ./.venv/bin/python scripts/reprocess_applications.py --user-id 1

Common examples:
  # Reprocess only needs_review=true (default)
  ./.venv/bin/python scripts/reprocess_applications.py --user-id 1

  # Reprocess everything for a user (ignore needs_review)
  ./.venv/bin/python scripts/reprocess_applications.py --user-id 1 --all

  # Reprocess low-confidence rows
  ./.venv/bin/python scripts/reprocess_applications.py --user-id 1 --min-confidence 0.7

  # Dry-run (no DB writes)
  ./.venv/bin/python scripts/reprocess_applications.py --user-id 1 --dry-run
"""

from __future__ import annotations

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
from app.models import User
from app.services.reprocess_service import ReprocessOptions, run_reprocess_applications


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reprocess applications in the database (LangGraph).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--user-id", type=int, default=None, help="User id to reprocess (required)")
    parser.add_argument("--user-email", type=str, default=None, help="Resolve user_id by email")
    parser.add_argument("--limit", type=int, default=500, help="Max rows to process (default: 500)")
    parser.add_argument("--batch-size", type=int, default=25, help="Rows per DB update batch (default: 25)")
    parser.add_argument("--min-confidence", type=float, default=None, help="Only rows with confidence < X")
    parser.add_argument("--only-needs-review", action="store_true", help="Only rows with needs_review=true (default)")
    parser.add_argument("--all", action="store_true", help="Reprocess all rows (ignore needs_review)")
    parser.add_argument("--after", type=str, default=None, help="Only rows received_date >= ISO/YYYY-MM-DD")
    parser.add_argument("--before", type=str, default=None, help="Only rows received_date <= ISO/YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Compute results but do not write to DB")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        user_id = args.user_id
        if args.user_email:
            u = db.query(User).filter(User.email == args.user_email.strip().lower()).first()
            if not u:
                print(f"User not found for --user-email: {args.user_email}", file=sys.stderr)
                return 2
            user_id = u.id
            print(f"Resolved --user-email to user_id={user_id}")

        if not user_id:
            print("ERROR: --user-id (or --user-email) is required", file=sys.stderr)
            return 2

        only_needs_review = True
        if args.all:
            only_needs_review = False
        if args.only_needs_review:
            only_needs_review = True

        options = ReprocessOptions(
            only_needs_review=only_needs_review,
            min_confidence=args.min_confidence,
            after_date=_parse_dt(args.after),
            before_date=_parse_dt(args.before),
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )

        def on_progress(processed: int, total: int, message: str):
            print(f"[{processed}/{total}] {message}", flush=True)

        print(
            "Reprocess starting:",
            f"user_id={user_id}",
            f"only_needs_review={options.only_needs_review}",
            f"min_confidence={options.min_confidence}",
            f"after={args.after}",
            f"before={args.before}",
            f"limit={options.limit}",
            f"batch_size={options.batch_size}",
            f"dry_run={options.dry_run}",
        )

        result = run_reprocess_applications(db, user_id=user_id, options=options, on_progress=on_progress)
        print("Reprocess done:", result)
        return 0 if int(result.get("errors", 0) or 0) == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

