FROM python:3.11-slim

# Prevent Python from writing .pyc and ensure logs flush.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (kept minimal; wheels cover most deps).
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy backend source.
COPY . /app

EXPOSE 8000

ENV TOKEN_PATH=/data/token.pickle

# Runtime dirs for token + temp files; create non-root user.
RUN mkdir -p /data \
  && useradd -m -u 10001 appuser \
  && chmod +x /app/docker-entrypoint.sh \
  && chown -R appuser:appuser /app /data

ENTRYPOINT ["/app/docker-entrypoint.sh"]
