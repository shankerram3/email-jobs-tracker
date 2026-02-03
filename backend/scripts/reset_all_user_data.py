#!/usr/bin/env python3
"""
Reset application-related data for ALL users (keeps users/accounts).

This is a destructive operation. By default it will refuse to run unless you pass
--yes-really.

Usage (from repo root):
  python backend/scripts/reset_all_user_data.py --yes-really

Usage (from backend/):
  ./.venv/bin/python scripts/reset_all_user_data.py --yes-really
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

# Ensure backend app is importable when run as script from backend or project root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.dirname(_script_dir)
if _backend not in sys.path:
    sys.path.insert(0, _backend)

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wipe application-related tables for all users (keeps users table).",
    )
    parser.add_argument(
        "--yes-really",
        action="store_true",
        help="Required. Actually perform the delete.",
    )
    parser.add_argument(
        "--delete-tokens",
        action="store_true",
        help="Also delete Gmail OAuth token files in TOKEN_DIR so users must re-authorize.",
    )
    args = parser.parse_args()

    if not args.yes_really:
        print(
            "Refusing to run without --yes-really.\n"
            "This will delete ALL application-related data for ALL users.\n"
            "Example:\n"
            "  python backend/scripts/reset_all_user_data.py --yes-really",
            file=sys.stderr,
        )
        return 2

    # Import the DB + models only after confirmation so we can safely print help/errors
    # even on environments that don't have DB drivers installed.
    try:
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.database import SessionLocal
        from app.models import (
            Application,
            EmailLog,
            SyncState,
            ReprocessState,
            OAuthState,
            ClassificationCache,
            SyncMetadata,
        )
    except ModuleNotFoundError as e:
        print(
            "ERROR: Missing a required dependency to connect to your database.\n"
            f"Missing module: {e}\n\n"
            "Fix:\n"
            "- Run this using your backend virtualenv (recommended), or\n"
            "- Install backend requirements: pip install -r backend/requirements.txt\n",
            file=sys.stderr,
        )
        return 1

    def _delete_all(db: Session, model) -> int:
        # Use bulk delete for speed; returns number of rows matched.
        return int(db.query(model).delete(synchronize_session=False) or 0)

    db: Session = SessionLocal()
    try:
        # Order matters for FK constraints (delete children before parents).
        # Plan: email_logs → applications → classification_cache → sync_state →
        #       reprocess_state → oauth_state → sync_metadata
        to_delete = [
            ("email_logs", EmailLog),
            ("applications", Application),
            ("classification_cache", ClassificationCache),
            ("sync_state", SyncState),
            ("reprocess_state", ReprocessState),
            ("oauth_state", OAuthState),
            ("sync_metadata", SyncMetadata),
        ]

        counts: dict[str, int] = {}
        try:
            for name, model in to_delete:
                try:
                    counts[name] = _delete_all(db, model)
                except Exception as e:
                    # If a table does not exist (e.g. fresh DB), treat as 0 rows.
                    if "no such table" in str(e).lower() or "does not exist" in str(e).lower():
                        counts[name] = 0
                    else:
                        raise
            db.commit()
        except Exception:
            db.rollback()
            raise

        print("Reset complete. Deleted rows:")
        for name, _model in to_delete:
            print(f"  - {name}: {counts.get(name, 0)}")

        if args.delete_tokens:
            token_dir = getattr(settings, "token_dir", "gmail_tokens")
            resolved = token_dir if os.path.isabs(token_dir) else os.path.join(_backend, token_dir)
            pattern = os.path.join(resolved, "token_*.pickle")
            removed = 0
            for path in glob.glob(pattern):
                try:
                    os.remove(path)
                    removed += 1
                except OSError as e:
                    print(f"  Warning: could not remove {path}: {e}", file=sys.stderr)
            print(f"\nToken files removed from {resolved}: {removed}")
        else:
            print("\nNOTE: Gmail OAuth tokens are stored on disk, not in the DB.")
            print("If you want all users to re-authorize Gmail, run with --delete-tokens or delete token files in TOKEN_DIR.")
            print("Common locations:")
            print("  - Local/dev default: backend/gmail_tokens/")
            print("  - Containers: /data/gmail_tokens/")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

