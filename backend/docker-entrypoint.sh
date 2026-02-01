#!/usr/bin/env sh
set -eu

# Defaults
: "${RUN_MIGRATIONS:=1}"
: "${PORT:=8000}"

# Optional: allow providing Gmail OAuth client JSON via env var (useful on PaaS).
# If set, we write it to CREDENTIALS_PATH (or /data/credentials.json by default).
if [ "${GMAIL_CREDENTIALS_JSON:-}" != "" ]; then
  : "${CREDENTIALS_PATH:=/data/credentials.json}"
  mkdir -p "$(dirname "$CREDENTIALS_PATH")"
  printf "%s" "$GMAIL_CREDENTIALS_JSON" > "$CREDENTIALS_PATH"
  chmod 600 "$CREDENTIALS_PATH" || true
fi

if [ "$RUN_MIGRATIONS" = "1" ]; then
  echo "[entrypoint] Running migrations..."
  alembic upgrade head
fi

echo "[entrypoint] Starting API..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

