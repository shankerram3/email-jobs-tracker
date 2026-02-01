#!/usr/bin/env bash
# Run from backend/: pip install -r requirements.txt, set .env, then:
set -euo pipefail
cd "$(dirname "$0")"

# Source of truth is backend/.env (loaded by pydantic-settings).
# Prevent any exported shell DATABASE_URL from overriding it.
unset DATABASE_URL || true

# Keep reload for dev, but avoid watching the venv/site-packages.
UVICORN_RELOAD_ARGS=(--reload --reload-dir "app" --reload-dir "alembic" --reload-exclude ".venv/*")

# Prefer the project's venv so dependencies (e.g. psycopg) are available.
if [ -x ".venv/bin/uvicorn" ]; then
  exec ".venv/bin/uvicorn" app.main:app "${UVICORN_RELOAD_ARGS[@]}" --host 0.0.0.0 --port 8000
elif [ -x ".venv/bin/python" ]; then
  exec ".venv/bin/python" -m uvicorn app.main:app "${UVICORN_RELOAD_ARGS[@]}" --host 0.0.0.0 --port 8000
else
  exec uvicorn app.main:app "${UVICORN_RELOAD_ARGS[@]}" --host 0.0.0.0 --port 8000
fi
