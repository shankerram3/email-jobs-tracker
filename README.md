# Job Application Tracker (Email Jobs Tracker)

Track job applications by syncing Gmail and classifying emails with AI. View stats, filter by status, and see a dashboard of applications (interviews, assessments, rejections, offers).

## Tech stack

- **Backend:** FastAPI (Python), Gmail API, OpenAI (email classification), SQLAlchemy (SQLite by default, PostgreSQL optional)
- **Frontend:** React, Vite, Recharts, Axios
- **Sync:** Background email fetch + AI classification with a progress bar in the UI

## Project structure

```
├── backend/           # FastAPI app
│   ├── app/
│   │   ├── main.py    # App entry, CORS, routers
│   │   ├── config.py  # Settings from env
│   │   ├── database.py
│   │   ├── models.py  # Application, EmailLog
│   │   ├── schemas.py
│   │   ├── gmail_service.py
│   │   ├── email_classifier.py  # OpenAI classification
│   │   ├── sync_state.py        # Sync progress state
│   │   ├── routers/   # /api/stats, /api/applications, /api/sync-emails, /api/sync-status
│   │   └── services/  # email_processor (run_sync)
│   ├── requirements.txt
│   └── run.sh
├── frontend/          # React + Vite
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js # Proxy /api -> backend
└── README.md
```

## Setup

### Backend

1. From the project root:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment:** Create `backend/.env`:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   ```
   Optional: `DATABASE_URL` for PostgreSQL (default is SQLite).

3. **Gmail:** Put your Google OAuth client secret in `backend/credentials.json` (download from [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → OAuth 2.0 Client IDs → download JSON). On first sync, a browser will open to authorize Gmail.

4. Run the API:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
   API: http://localhost:8000 — Docs: http://localhost:8000/docs

### Frontend

1. From the project root:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   App: http://localhost:5173 (proxies `/api` to the backend).

## Usage

1. Start backend and frontend (see above).
2. In the app, click **Sync Emails**. Authorize Gmail if prompted.
3. The progress bar shows fetch + classification; when done, stats and the applications table update.
4. Use filters (All, Interviews, Assessments, Rejections, Offers) to narrow the list.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Application counts (total, interviews, assessments, rejections, offers, pending) |
| GET | `/api/applications` | List applications (query: `status`, `limit`) |
| POST | `/api/sync-emails` | Start background email sync |
| GET | `/api/sync-status` | Current sync progress (status, message, processed, total, created, skipped, errors) |

## License

MIT
