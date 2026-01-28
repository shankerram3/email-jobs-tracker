#!/usr/bin/env bash
# Run from backend/: pip install -r requirements.txt, set .env, then:
cd "$(dirname "$0")"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
