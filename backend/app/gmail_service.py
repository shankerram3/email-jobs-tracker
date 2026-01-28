"""Gmail API integration."""
import base64
import os
import pickle
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _resolve_path(path: str) -> str:
    """Resolve path relative to backend dir if not absolute."""
    if os.path.isabs(path):
        return path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, path)


def get_gmail_service():
    creds = None
    token_path = _resolve_path(settings.token_path)
    creds_path = _resolve_path(settings.credentials_path)

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Download from Google Cloud Console and save as credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def _get_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    if "parts" not in payload:
        return ""
    for part in payload["parts"]:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            raw = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            # Strip tags for classifier
            import re
            return re.sub(r"<[^>]+>", " ", raw)[:2000]
    return ""


def _get_headers(email: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in email.get("payload", {}).get("headers", [])}


def _get_received_date(email: dict):
    headers = _get_headers(email)
    date_str = headers.get("date")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def fetch_emails(service, query: str, max_results: int = 100):
    """Fetch full email messages matching query."""
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        email = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="full")
            .execute()
        )
        emails.append(email)
    return emails


def email_to_parts(email: dict) -> tuple[str, str, str, str, str]:
    """Return (message_id, subject, sender, body, received_date_iso)."""
    mid = email.get("id", "")
    headers = _get_headers(email)
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    body = _get_body(email.get("payload", {}))
    received = _get_received_date(email)
    received_iso = received.isoformat() if received else None
    return mid, subject, sender, body, received_iso
