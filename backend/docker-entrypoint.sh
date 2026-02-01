#!/usr/bin/env sh
set -eu

# Defaults
: "${RUN_MIGRATIONS:=1}"

if [ "$RUN_MIGRATIONS" = "1" ]; then
  echo "[entrypoint] Running migrations..."
  alembic upgrade head
fi

echo "[entrypoint] Starting API..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

