"""Gmail API integration: history-based incremental sync, pagination, rate limiting."""
import base64
import os
import pickle
import secrets
import time
import re
import logging
from email.utils import parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings

# CSRF state for OAuth when gmail_oauth_redirect_uri is set: state -> {redirect_url, created_at}
_oauth_state_store: dict[str, dict] = {}
_oauth_state_lock = __import__("threading").Lock()
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, path)


class GmailAuthRequiredError(Exception):
    """Raised when Gmail needs interactive OAuth (browser). Do not run in background task."""
    pass


def _gmail_creds_ready_for_background() -> bool:
    """True if we can get a service without blocking on browser OAuth."""
    token_path = _resolve_path(settings.token_path)
    creds_path = _resolve_path(settings.credentials_path)
    if not os.path.exists(creds_path):
        return False
    if not os.path.exists(token_path):
        return False
    try:
        with open(token_path, "rb") as token:
            creds = pickle.load(token)
    except Exception:
        return False
    if not creds:
        return False
    if creds.valid:
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            return creds.valid
        except Exception:
            return False
    return False


def _clean_oauth_states():
    """Remove expired state entries."""
    now = time.time()
    with _oauth_state_lock:
        expired = [s for s, v in _oauth_state_store.items() if now - v.get("created_at", 0) > OAUTH_STATE_TTL_SECONDS]
        for s in expired:
            _oauth_state_store.pop(s, None)


def start_gmail_oauth(redirect_url_after: str) -> str:
    """
    Start OAuth with CSRF state. Use when gmail_oauth_redirect_uri is set.
    Returns the Google authorization URL to redirect the user to.
    Call finish_gmail_oauth(code, state) in the callback.
    """
    creds_path = _resolve_path(settings.credentials_path)
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Gmail credentials not found at {creds_path}. "
            "Download from Google Cloud Console and save as credentials.json"
        )
    redirect_uri = settings.gmail_oauth_redirect_uri
    if not redirect_uri:
        raise ValueError("GMAIL_OAUTH_REDIRECT_URI must be set to use start_gmail_oauth")
    state = secrets.token_urlsafe(32)
    with _oauth_state_lock:
        _oauth_state_store[state] = {"redirect_url": redirect_url_after, "created_at": time.time()}
    _clean_oauth_states()
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(prompt="consent", state=state, access_type="offline")
    return auth_url


def finish_gmail_oauth(code: str, state: str) -> str:
    """
    Validate state and exchange code for tokens. Returns redirect_url to send the user to.
    Raises ValueError if state is invalid or expired.
    """
    _clean_oauth_states()
    with _oauth_state_lock:
        entry = _oauth_state_store.pop(state, None)
    if not entry:
        raise ValueError("Invalid or expired OAuth state")
    redirect_url = entry.get("redirect_url", "http://localhost:5173")
    creds_path = _resolve_path(settings.credentials_path)
    token_path = _resolve_path(settings.token_path)
    flow = InstalledAppFlow.from_client_secrets_file(
        creds_path, SCOPES, redirect_uri=settings.gmail_oauth_redirect_uri
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    with open(token_path, "wb") as token:
        pickle.dump(creds, token)
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return redirect_url


def get_gmail_service(allow_interactive_oauth: bool = False):
    """
    Return Gmail API service. If allow_interactive_oauth is False (default) and
    we would need to open a browser (run_local_server), raises GmailAuthRequiredError
    so the caller can show a message instead of blocking forever in a background task.
    """
    creds = None
    token_path = _resolve_path(settings.token_path)
    creds_path = _resolve_path(settings.credentials_path)

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                if not allow_interactive_oauth:
                    raise GmailAuthRequiredError(
                        "Gmail token expired and refresh failed. Open /api/gmail/auth in your browser to sign in again."
                    ) from e
                raise
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Download from Google Cloud Console and save as credentials.json"
                )
            if not allow_interactive_oauth:
                raise GmailAuthRequiredError(
                    "Gmail authorization required. Open /api/gmail/auth in your browser to sign in, then try Sync again."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass

    return build("gmail", "v1", credentials=creds)


def _get_body(payload: dict) -> str:
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    if "parts" not in payload:
        return ""
    for part in payload["parts"]:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            raw = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
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


# Rate limiting: exponential backoff
def _with_backoff(fn, max_retries: int = 5):
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def get_profile_history_id(service) -> Optional[str]:
    """Return the user's current historyId from Gmail profile."""
    try:
        profile = _with_backoff(
            lambda: service.users().getProfile(userId="me").execute()
        )
        return profile.get("historyId")
    except Exception:
        return None


def list_history(
    service,
    start_history_id: str,
    max_results: int = 100,
    page_token: Optional[str] = None,
) -> dict:
    """Fetch history list (deltas). Paginated."""
    return _with_backoff(
        lambda: service.users()
        .history()
        .list(
            userId="me",
            startHistoryId=start_history_id,
            maxResults=min(max_results, settings.gmail_history_max_results),
            pageToken=page_token or None,
            historyTypes=["messageAdded", "messageDeleted"],
        )
        .execute()
    )


def list_messages(
    service,
    query: str,
    max_results: int = 100,
    page_token: Optional[str] = None,
) -> dict:
    """List message IDs with pagination."""
    return _with_backoff(
        lambda: service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=min(max_results, settings.gmail_messages_max_results),
            pageToken=page_token or None,
        )
        .execute()
    )


def get_message(service, msg_id: str) -> dict:
    """Get full message by ID."""
    return _with_backoff(
        lambda: service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )


def fetch_emails(service, query: str, max_results: int = 100):
    """Fetch full email messages matching query. Paginated."""
    all_emails = []
    page_token = None
    page_size = min(settings.gmail_sync_page_size, max_results, 100)
    page_num = 0

    logger.info(f"    Starting fetch with page_size={page_size}, max_results={max_results}")

    while True:
        page_num += 1
        logger.info(f"    Page {page_num}: Fetching message list...")
        result = list_messages(service, query, max_results=page_size, page_token=page_token)
        messages = result.get("messages", [])
        logger.info(f"    Page {page_num}: Got {len(messages)} message IDs")

        for idx, msg in enumerate(messages, 1):
            if idx % 10 == 0:
                logger.info(f"      Fetching message {idx}/{len(messages)} (total: {len(all_emails) + idx})")
            email = get_message(service, msg["id"])
            all_emails.append(email)

        logger.info(f"    Page {page_num} complete: {len(all_emails)} total messages so far")
        page_token = result.get("nextPageToken")
        if not page_token or len(all_emails) >= max_results:
            break
    logger.info(f"    Finished: {len(all_emails)} total messages")
    return all_emails


def fetch_emails_from_history(
    service,
    start_history_id: str,
    on_progress=None,
) -> tuple[list[dict], Optional[str], bool]:
    """
    Incremental sync via history.list. Returns (emails, new_history_id, history_too_old).
    If historyId too old, returns ([], None, True) and caller should fall back to full sync.
    """
    all_message_ids = set()
    current_history_id = start_history_id
    new_history_id = start_history_id
    page_token = None
    history_too_old = False

    while True:
        try:
            result = list_history(
                service,
                start_history_id=current_history_id,
                max_results=settings.gmail_history_max_results,
                page_token=page_token,
            )
        except HttpError as e:
            if e.resp.status == 404 or "historyId" in (e.reason or "").lower():
                history_too_old = True
                return [], None, True
            raise

        for record in result.get("history", []):
            for msg in record.get("messagesAdded", []):
                all_message_ids.add(msg["message"]["id"])
            for msg in record.get("messagesDeleted", []):
                all_message_ids.discard(msg["message"]["id"])

        new_history_id = result.get("historyId") or current_history_id
        page_token = result.get("nextPageToken")
        if page_token:
            current_history_id = new_history_id
            if on_progress:
                on_progress(len(all_message_ids), "Fetching history…")
        else:
            break

    emails = []
    for i, mid in enumerate(all_message_ids):
        try:
            email = get_message(service, mid)
            emails.append(email)
        except HttpError:
            continue
        if on_progress and (i + 1) % 10 == 0:
            on_progress(i + 1, f"Fetching message {i + 1}/{len(all_message_ids)}…")
    return emails, new_history_id, False


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
