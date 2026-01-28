"""Unit tests for Gmail pagination and history sync logic."""
import pytest
from unittest.mock import MagicMock, patch

from app.gmail_service import (
    list_messages,
    list_history,
    fetch_emails_from_history,
    email_to_parts,
)


def test_email_to_parts():
    """Test extraction of message_id, subject, sender, body, date from email dict."""
    email = {
        "id": "msg123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Interview at Acme"},
                {"name": "From", "value": "hr@acme.com"},
                {"name": "Date", "value": "Mon, 01 Jan 2024 12:00:00 +0000"},
            ],
            "body": {"data": "aGVsbG8="},
        },
    }
    mid, subject, sender, body, received_iso = email_to_parts(email)
    assert mid == "msg123"
    assert subject == "Interview at Acme"
    assert sender == "hr@acme.com"
    assert body == "hello"
    assert received_iso is not None


def test_list_messages_pagination():
    """Test that list_messages is called with page_token when provided."""
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "1"}],
        "nextPageToken": "token2",
    }
    with patch("app.gmail_service._with_backoff", side_effect=lambda fn: fn()):
        result = list_messages(service, "query", max_results=10, page_token="token1")
    assert result["messages"] == [{"id": "1"}]
    assert result["nextPageToken"] == "token2"
    call = service.users.return_value.messages.return_value.list.return_value.execute
    assert call.called


def test_fetch_emails_from_history_returns_tuple():
    """Test fetch_emails_from_history returns (emails, new_history_id, history_too_old)."""
    service = MagicMock()
    service.users.return_value.history.return_value.list.return_value.execute.return_value = {
        "history": [],
        "historyId": "12345",
    }
    with patch("app.gmail_service._with_backoff", side_effect=lambda fn: fn()):
        emails, new_id, too_old = fetch_emails_from_history(service, "100")
    assert new_id == "12345"
    assert too_old is False
    assert isinstance(emails, list)
