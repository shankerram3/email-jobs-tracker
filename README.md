# Job Application Tracker (Email Jobs Tracker)

Track job applications by syncing Gmail (history-based incremental sync), classifying emails with AI (structured extraction + cache), and viewing analytics. Real-time sync progress via SSE; optional JWT or API key auth.

---

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Database schema](#database-schema)
- [Environment variables](#environment-variables)
- [Setup](#setup)
- [Sync modes and Gmail auth](#sync-modes-and-gmail-auth)
- [API reference](#api-reference)
- [Analytics](#analytics)
- [Testing](#testing)
- [Migration and security](#migration-and-security)
- [License](#license)

---

## Overview

- **Purpose:** Ingest job-related emails from Gmail, classify them (rejection, interview request, assessment, offer) with AI, store applications in a database, and provide funnel/response-rate/time-to-event analytics plus a simple success-prediction model.
- **Flow:** Gmail OAuth in browser → sync (full or incremental) → fetch messages → classify (OpenAI + cache) → persist to DB → expose via REST + SSE progress.

---

## Architecture

### Components

| Component | Role |
|-----------|------|
| **FastAPI backend** | REST API, Gmail OAuth redirect, sync orchestration, SSE stream |
| **Gmail service** | History API for incremental sync; search + pagination for full sync; rate limit/backoff |
| **Email processor** | Fetches messages, dedupes, runs classification (cache + LLM + regex fallback), writes to DB |
| **Classification service** | Content hash → cache lookup; on miss: structured LLM extraction; company normalization |
| **Sync state** | In-memory progress (processed/total/message) for `/sync-status` and SSE; DB state (historyId, last_synced_at) for incremental |
| **Celery (optional)** | Async sync task; requires Redis as broker (if not used, sync runs in-process via BackgroundTasks) |
| **Frontend** | React + Vite; lists applications, triggers sync, shows SSE progress; analytics dashboard |

### Data flow

1. **Auth:** User opens `/api/gmail/auth` in browser → OAuth flow → token stored (e.g. `token.pickle`). Backend checks credentials are “ready for background” before starting sync.
2. **Sync start:** `POST /api/sync-emails?mode=auto|full|incremental` → background task starts.
3. **Sync execution:**  
   - **Auto:** If no historyId or no applications yet → full sync; else incremental (history).  
   - **Full:** Gmail search (subject/from) with pagination; optional `gmail_full_sync_after_date` / `gmail_full_sync_days_back` / `gmail_full_sync_ignore_last_synced`.  
   - **Incremental:** Gmail history API from stored `last_history_id`.  
   Emails are fetched first; only after the fetch phase, classification runs and results are written to `applications` and `email_logs`.
4. **Progress:** In-memory state updated (processed, total, message); clients poll `/api/sync-status` or subscribe to `/api/sync-events` (SSE) until status is `idle` or `error`.
5. **Analytics:** Funnel, response-rate (by company/industry), time-to-event (rejection/interview), and prediction endpoint read from `applications` (and related tables as needed).

---

## Tech stack

- **Backend:** FastAPI (Python), Gmail API (history + search), OpenAI (structured classification), SQLAlchemy (SQLite/PostgreSQL), Alembic (migrations), Celery + Redis (optional async jobs), SSE (sync progress)
- **Frontend:** React, Vite, Recharts, Axios
- **Auth:** JWT (HS256) or static API key in header. Protected endpoints (applications, sync, analytics) require authentication; if neither `SECRET_KEY` nor `API_KEY` is set, those routes return 401. Set at least one for normal use (e.g. `SECRET_KEY` and use `POST /api/login`, or `API_KEY` in header).

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, routers
│   │   ├── config.py            # Settings from .env
│   │   ├── database.py          # Session, init_db
│   │   ├── models.py            # Application, EmailLog, SyncMetadata, SyncState, Company, ClassificationCache
│   │   ├── schemas.py           # Pydantic request/response models
│   │   ├── auth.py              # JWT + API key, get_current_user
│   │   ├── gmail_service.py     # Gmail API, history, pagination, rate limit
│   │   ├── email_classifier.py  # Structured LLM + cache hash + regex fallback
│   │   ├── sync_state.py        # In-memory sync progress
│   │   ├── sync_state_db.py    # DB sync state (historyId, etc.)
│   │   ├── celery_app.py       # Celery app (broker = Redis)
│   │   ├── tasks.py             # Celery sync task
│   │   ├── routers/
│   │   │   ├── applications.py  # /stats, /applications, /applications/{id}, schedule, respond
│   │   │   ├── sync.py          # /gmail/auth, /sync-emails, /sync-status, /sync-events
│   │   │   ├── analytics.py     # /funnel, /response-rate, /time-to-event, /prediction
│   │   │   └── auth_router.py  # /login
│   │   └── services/
│   │       ├── email_processor.py    # run_sync_with_options, fetch + classify + persist
│   │       └── classification_service.py
│   ├── alembic/                 # Migrations
│   ├── tests/
│   ├── requirements.txt
│   ├── run.sh                   # uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
│   └── .env                     # Secrets (do not commit)
├── frontend/
│   └── src/
│       ├── App.jsx
│       ├── main.jsx
│       └── index.css
└── README.md
```

---

## Database schema

### Tables

| Table | Purpose |
|-------|---------|
| **applications** | One row per classified job email: company_name, position, status, category, subcategory, job_title, salary_min/max, location, confidence, email_* fields, received_date, applied_at/rejected_at/interview_at/offer_at, linkedin_url, created_at, updated_at. `gmail_message_id` unique. |
| **email_logs** | Processed Gmail message IDs, processed_at, classification, error (for idempotency/debug). |
| **sync_metadata** | Key-value (e.g. last_synced_at) for backward compatibility. |
| **sync_state** | last_history_id, last_synced_at, last_full_sync_at, status (idle/syncing/error), error, updated_at. |
| **companies** | canonical_name, aliases (JSON), industry. |
| **classification_cache** | content_hash (unique), category, subcategory, company_name, job_title, salary_min/max, location, confidence, raw_json, created_at. |

### Indexes (applications)

- `ix_applications_category_received_date`
- `ix_applications_status_received_date`
- `ix_applications_received_date`
- Plus indexes on id, gmail_message_id, company_name, category, subcategory, job_title.

---

## Environment variables

Create `backend/.env` (do not commit). All settings are read via `config.Settings` (pydantic-settings from `.env`).

| Variable | Default | Description |
|----------|---------|-------------|
| **Database** | | |
| `DATABASE_URL` | `sqlite:///./job_tracker.db` | SQLAlchemy URL (SQLite or PostgreSQL). |
| **Gmail** | | |
| `credentials_path` | `credentials.json` | Path to Google OAuth client JSON (relative to backend or absolute). |
| `token_path` | `token.pickle` | Path to store OAuth token. |
| `GMAIL_OAUTH_REDIRECT_URI` | (none) | If set, OAuth uses this as redirect_uri (e.g. `http://localhost:8000/api/gmail/callback`) and validates a CSRF `state` parameter. Add this exact URI to your Google OAuth client’s redirect URIs. |
| **AI** | | |
| `OPENAI_API_KEY` | `""` | Required for LLM classification. |
| **CORS** | | |
| `CORS_ORIGINS` | `["http://localhost:3000", "http://localhost:5173"]` | Allowed origins (list). |
| **Redis / Celery** | | |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL (Celery broker and optional cache). |
| `CELERY_BROKER_URL` | (uses REDIS_URL) | Override Celery broker. |
| **Auth** | | |
| `SECRET_KEY` | `""` | JWT signing key; if set, login returns JWT. Required for protected routes unless `API_KEY` is set. |
| `API_KEY` | `""` | Optional static API key (sent in header). When set, protected routes accept this instead of JWT. |
| `API_KEY_HEADER` | `X-API-Key` | Header name for API key. |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm. |
| `JWT_EXPIRE_MINUTES` | `10080` | JWT expiry (7 days). |
| **Gmail limits / full sync** | | |
| `GMAIL_HISTORY_MAX_RESULTS` | `100` | History API batch size. |
| `GMAIL_MESSAGES_MAX_RESULTS` | `100` | Messages per request. |
| `GMAIL_SYNC_PAGE_SIZE` | `100` | Pagination page size. |
| `GMAIL_FULL_SYNC_MAX_PER_QUERY` | `2000` | Max emails per full-sync query. |
| `GMAIL_FULL_SYNC_AFTER_DATE` | (none) | Override “after” date for full sync (YYYY/MM/DD or YYYY-MM-DD). |
| `GMAIL_FULL_SYNC_DAYS_BACK` | `90` | Days back for full sync when no override date. |
| `GMAIL_FULL_SYNC_IGNORE_LAST_SYNCED` | `false` | If true, ignore last_synced_at for full sync and use after_date/days_back. |

---

## Setup

### Backend

1. From project root:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment:** Create `backend/.env` and set at least:
   - `OPENAI_API_KEY` — required for email classification
   - `DATABASE_URL` — optional (default SQLite)
   - `REDIS_URL` — if using Celery (default `redis://localhost:6379/0`)
   - `SECRET_KEY` — for JWT; use `POST /api/login` to get a token (or set `API_KEY` for header auth)
   - `API_KEY` — optional static API key (header: `X-API-Key` by default). Protected routes require either JWT or API key.

3. **Gmail OAuth:** Place Google OAuth client JSON at `backend/credentials.json` (APIs & Services → Credentials → OAuth 2.0 Client ID → download JSON). Then open **`GET /api/gmail/auth`** in a browser to authorize; after that, sync can run in the background.

4. **Migrations:**
   ```bash
   cd backend
   alembic upgrade head
   ```

5. **Run API:**
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
   API: http://localhost:8000 — Docs: http://localhost:8000/docs

6. **Optional — Celery worker** (async sync; otherwise sync runs in-process):
   ```bash
   celery -A app.celery_app worker -l info
   ```
   Ensure Redis is running (`redis-server`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173 (proxies `/api` to backend).

---

## Sync modes and Gmail auth

- **Auto (`mode=auto`):** If there is no stored historyId or no applications yet, runs a **full** sync; otherwise runs **incremental** (Gmail history). Default for `POST /api/sync-emails`.
- **Full (`mode=full`):** Gmail search by subject/from, paginated; respects `GMAIL_FULL_SYNC_*` (max per query, after date, days back, ignore last_synced).
- **Incremental (`mode=incremental`):** Uses `sync_state.last_history_id` and Gmail history API.

**Gmail auth:** Sync must have valid OAuth credentials. The backend checks “credentials ready for background” before starting. If not, it returns 400 and tells the user to open **`GET /api/gmail/auth`** in the browser. Optional query: `?redirect_url=http://localhost:5173` to return to the app after auth. For CSRF protection, set **`GMAIL_OAUTH_REDIRECT_URI`** (e.g. `http://localhost:8000/api/gmail/callback`) and add that URI to your Google OAuth client; the flow will use **`GET /api/gmail/callback`** and validate the `state` parameter.

---

## API reference

Base URL: `http://localhost:8000`. Auth: `Authorization: Bearer <JWT>` or `X-API-Key: <key>` when configured.

### Applications

| Method | Path | Query / Body | Description |
|--------|------|--------------|-------------|
| GET | `/api/stats` | — | Application counts (total, rejections, interviews, assessments, pending, offers). |
| GET | `/api/applications` | `status`, `offset`, `limit` (default 50, max 100) | Paginated list; `status` filters by category (e.g. REJECTION, INTERVIEW_REQUEST) or omit for all. |
| GET | `/api/applications/{id}` | — | Single application details. |
| POST | `/api/applications/{id}/schedule` | Body: `calendar_event_at`, `title`, `description` | Placeholder for calendar scheduling. |
| POST | `/api/applications/{id}/respond` | Body: `message`, `template` | Placeholder for sending a reply. |

### Sync

| Method | Path | Query / Body | Description |
|--------|------|--------------|-------------|
| GET | `/api/gmail/auth` | Optional: `redirect_url` | Redirects to Gmail OAuth; after consent, redirects to `redirect_url` or localhost:5173. When `GMAIL_OAUTH_REDIRECT_URI` is set, uses CSRF state. |
| GET | `/api/gmail/callback` | `code`, `state` (from Google) | OAuth callback when `GMAIL_OAUTH_REDIRECT_URI` is set; validates state and exchanges code for token. |
| POST | `/api/sync-emails` | Query: `mode=auto\|incremental\|full` | Start sync in background; returns immediately. |
| GET | `/api/sync-status` | — | Current sync progress for this user: status, message, processed, total, created, skipped, errors, error. |
| GET | `/api/sync-events` | Optional: `token` (for SSE without custom headers) | SSE stream of sync progress for this user until status is idle or error. |

### Analytics

| Method | Path | Query | Description |
|--------|------|-------|-------------|
| GET | `/api/analytics/funnel` | — | Funnel: Applied → Interview → Offer; plus Rejection count and percentages. |
| GET | `/api/analytics/response-rate` | `group_by=company\|industry` | Response rate by company or by industry (category). |
| GET | `/api/analytics/time-to-event` | `event=rejection\|interview` | Median and average days from received_date to event. |
| GET | `/api/analytics/prediction` | `limit` (1–100, default 50) | Success prediction (logistic regression MVP); returns application_id, company_name, probability, features. |

### Auth

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/login` | `{"username": "..."}` | Returns JWT; requires `SECRET_KEY`. |

---

## Analytics

- **Funnel:** Counts applied, interview (INTERVIEW_REQUEST + ASSESSMENT), offer, rejection; percentages of total.
- **Response rate:** By company or by industry (category); applied vs responded (rejection/interview/assessment/offer); rate = responded / applied.
- **Time-to-event:** From `received_date` to `rejected_at` or `interview_at`; median and average days; sample size.
- **Prediction:** Simple logistic regression over recent applications (category one-hot, days_since_received); target = offer or interview; returns top N with probability (requires `sklearn`).

---

## Testing

Backend tests live under `backend/tests/`. Run with pytest from the backend directory:

```bash
cd backend
pytest
```

(Adjust for your test layout and markers if any.)

---

## Migration and security

- **DB:** Run `alembic upgrade head` to apply migrations. New columns on `applications` are nullable; new tables (`sync_state`, `companies`, `classification_cache`) are created by migrations.
- **Secrets:** Keep all sensitive config in `backend/.env`. Do **not** commit `.env` or `credentials.json` (add them to `.gitignore`).
- **OAuth CSRF:** When `GMAIL_OAUTH_REDIRECT_URI` is set, the Gmail OAuth flow uses a cryptographically random `state` parameter, stores it server-side, and validates it on callback to mitigate CSRF. Without that redirect URI, the local `run_local_server` flow does not use state.
- **Token storage:** JWTs are typically stored in the frontend (e.g. localStorage). This is convenient but increases exposure if XSS occurs; consider HTTP-only cookies or stronger CSP/sanitization for production. Gmail OAuth tokens are written to `token.pickle` with file mode `0o600`; the file is unencrypted—for production, consider encrypting at rest or using a secrets manager.

---

## License

MIT
