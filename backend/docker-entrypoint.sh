#!/usr/bin/env sh
set -eu

# Defaults
: "${RUN_MIGRATIONS:=1}"
: "${PORT:=8000}"

# Ensure /data exists and is writable (Railway volumes may mount root-owned).
# If this fails, we will fall back to /tmp (non-persistent).
mkdir -p /data 2>/dev/null || true
if [ -w /data ]; then
  :
else
  # Try to make it writable if we are running as root.
  if [ "$(id -u)" = "0" ]; then
    chmod 777 /data 2>/dev/null || true
  fi
fi

# If still not writable, fall back to /tmp paths so the app can start.
if [ ! -w /data ]; then
  echo "[entrypoint] WARNING: /data is not writable; falling back to /tmp (OAuth token will not persist across restarts)."
  : "${CREDENTIALS_PATH:=/tmp/credentials.json}"
  : "${TOKEN_PATH:=/tmp/token.pickle}"
  : "${TOKEN_DIR:=/tmp/gmail_tokens}"
fi

# Ensure TOKEN_DIR exists if set (best-effort).
if [ "${TOKEN_DIR:-}" != "" ]; then
  mkdir -p "$TOKEN_DIR" 2>/dev/null || true
fi

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
# Trust X-Forwarded-* headers from the platform proxy (Railway/Cloudflare)
# so request.url.scheme/host are correct for OAuth redirects.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"

