#
# Single-container build: FastAPI serves the built React frontend.
#

FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Where FastAPI will look for built frontend assets
    FRONTEND_DIST_DIR=/app/frontend_dist

WORKDIR /app/backend

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY --from=frontend-build /frontend/dist /app/frontend_dist

# Persist Gmail OAuth token between restarts (mount /data if desired).
RUN mkdir -p /data \
  && useradd -m -u 10001 appuser \
  && chmod +x /app/backend/docker-entrypoint.sh \
  && chown -R appuser:appuser /app /data

ENV TOKEN_PATH=/data/token.pickle

EXPOSE 8000

ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]

