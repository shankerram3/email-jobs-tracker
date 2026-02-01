"""Gmail API integration: history-based incremental sync, pagination, rate limiting."""
import base64
import os
import pickle
import secrets
import time
import re
import logging
import threading
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings
from .oauth_state_db import KIND_GMAIL, oauth_state_set, oauth_state_consume

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, path)


def _token_path_for_user(user_id: Optional[int]) -> str:
    """
    Resolve Gmail token path for a given user.

    - If TOKEN_DIR is set and user_id is provided, store tokens at:
      TOKEN_DIR/token_<user_id>.pickle
    - Otherwise, fall back to legacy TOKEN_PATH (single shared token file).
    """
    token_dir = getattr(settings, "token_dir", None)
    if token_dir and user_id is None:
        raise ValueError("TOKEN_DIR is set; user_id is required for Gmail token access")
    if user_id is not None and token_dir:
        resolved_dir = _resolve_path(token_dir)
        return os.path.join(resolved_dir, f"token_{user_id}.pickle")
    return _resolve_path(settings.token_path)


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


class GmailAuthRequiredError(Exception):
    """Raised when Gmail needs interactive OAuth (browser). Do not run in background task."""
    pass


def _gmail_creds_ready_for_background(user_id: Optional[int]) -> bool:
    """True if we can get a service without blocking on browser OAuth."""
    token_path = _token_path_for_user(user_id)
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


def start_gmail_oauth(redirect_url_after: str, user_id: int) -> str:
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
    oauth_state_set(KIND_GMAIL, state, redirect_url_after, user_id=user_id)
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(prompt="consent", state=state, access_type="offline")
    return auth_url


def finish_gmail_oauth(code: str, state: str) -> str:
    """
    Validate state and exchange code for tokens. Returns redirect_url to send the user to.
    Raises ValueError if state is invalid or expired.
    """
    entry = oauth_state_consume(state)
    if not entry:
        raise ValueError("Invalid or expired OAuth state")
    if entry.get("kind") != KIND_GMAIL:
        raise ValueError("Invalid or expired OAuth state")
    # Always prefer stored redirect_url; fall back to configured CORS origin (prod-safe) then localhost.
    redirect_url = entry.get("redirect_url") or (settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173")
    creds_path = _resolve_path(settings.credentials_path)
    user_id = entry.get("user_id")
    if getattr(settings, "token_dir", None) and user_id is None:
        # Enforce user binding when TOKEN_DIR is enabled (multi-user safe default).
        raise ValueError("Invalid OAuth state (missing user binding)")
    token_path = _token_path_for_user(user_id) if user_id is not None else _resolve_path(settings.token_path)
    _ensure_parent_dir(token_path)
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


def get_gmail_service(user_id: Optional[int] = None, allow_interactive_oauth: bool = False):
    """
    Return Gmail API service. If allow_interactive_oauth is False (default) and
    we would need to open a browser (run_local_server), raises GmailAuthRequiredError
    so the caller can show a message instead of blocking forever in a background task.
    """
    if getattr(settings, "token_dir", None) and user_id is None:
        raise ValueError("TOKEN_DIR is set; user_id is required for Gmail token access")
    creds = None
    token_path = _token_path_for_user(user_id)
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
        _ensure_parent_dir(token_path)
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
        except (ssl.SSLError, OSError) as e:
            # Network/TLS flakiness can happen on some platforms; retry a few times.
            if attempt < max_retries - 1:
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
    max_pages = int(getattr(settings, "gmail_sync_max_pages", 2000))

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
        next_page_token = result.get("nextPageToken")
        if next_page_token is not None and next_page_token == page_token:
            logger.warning("    Pagination stalled (repeated page token); stopping fetch.")
            break
        page_token = next_page_token
        if page_num >= max_pages:
            logger.warning("    Pagination hit max page limit; stopping fetch.")
            break
        if not page_token or len(all_emails) >= max_results:
            break
    logger.info(f"    Finished: {len(all_emails)} total messages")
    return all_emails


def fetch_emails_parallel(
    service,
    queries: List[str],
    max_results_per_query: int = 100,
    max_workers: int = 7,
    on_progress: Optional[Callable[[int, str], None]] = None,
    service_factory: Optional[Callable[[], object]] = None,
) -> List[dict]:
    """
    Fetch emails from multiple Gmail queries in parallel.
    Returns deduplicated list of full email messages.

    Args:
        service: Gmail API service instance
        queries: List of Gmail search queries to run in parallel
        max_results_per_query: Max results for each query
        max_workers: Number of parallel threads (default 7 for 7 queries)
        on_progress: Optional callback(count, message) for progress updates

    Returns:
        List of unique email dicts (deduplicated by message ID)
    """
    all_emails: List[dict] = []
    seen_ids: set[str] = set()
    results_lock = threading.Lock()
    query_errors: List[str] = []

    def fetch_one(query: str, query_idx: int):
        """Fetch emails for a single query."""
        try:
            # NOTE: googleapiclient service objects are not thread-safe.
            # Use a per-thread service when running in parallel to avoid TLS/connection corruption.
            local_service = service_factory() if service_factory else service
            emails = fetch_emails(local_service, query, max_results=max_results_per_query)
            return (query_idx, emails, None)
        except Exception as e:
            return (query_idx, [], str(e))

    logger.info(f"Starting parallel fetch of {len(queries)} queries with {max_workers} workers")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_one, q, i): (i, q)
            for i, q in enumerate(queries)
        }

        for future in as_completed(futures):
            idx, emails, error = future.result()

            if error:
                logger.error(f"Query {idx+1}/{len(queries)} failed: {error}")
                query_errors.append(error)
                continue

            new_count = 0
            with results_lock:
                for email in emails:
                    msg_id = email.get("id")
                    if msg_id and msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        all_emails.append(email)
                        new_count += 1

            logger.info(f"Query {idx+1}/{len(queries)}: {len(emails)} emails, {new_count} unique (total: {len(all_emails)})")

            if on_progress:
                on_progress(len(all_emails), f"Query {idx+1}/{len(queries)} complete")

    logger.info(f"Parallel fetch complete: {len(all_emails)} unique emails from {len(queries)} queries")

    if query_errors and not all_emails:
        raise Exception(f"All queries failed: {query_errors[0]}")

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
