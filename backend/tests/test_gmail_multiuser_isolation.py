import os
import pickle


def test_gmail_auth_requires_auth(client):
    # /api/gmail/auth is now tied to an authenticated user (no anonymous OAuth).
    resp = client.get("/api/gmail/auth")
    assert resp.status_code in (401, 403)


def test_token_path_is_per_user_when_token_dir_set(monkeypatch, tmp_path):
    from app.config import settings
    from app import gmail_service

    token_dir = tmp_path / "gmail_tokens"
    monkeypatch.setattr(settings, "token_dir", str(token_dir), raising=False)
    monkeypatch.setattr(settings, "token_path", "token.pickle", raising=False)

    p = gmail_service._token_path_for_user(123)
    assert os.path.basename(p) == "token_123.pickle"
    assert os.path.dirname(p) == str(token_dir)


def test_finish_gmail_oauth_enforces_user_binding_when_token_dir_enabled(monkeypatch, tmp_path):
    from app.config import settings
    from app import gmail_service

    token_dir = tmp_path / "gmail_tokens"
    monkeypatch.setattr(settings, "token_dir", str(token_dir), raising=False)
    monkeypatch.setattr(settings, "gmail_oauth_redirect_uri", "http://localhost:8000/api/gmail/callback", raising=False)

    # If token_dir is enabled, the OAuth state must be bound to a user_id.
    monkeypatch.setattr(
        gmail_service,
        "oauth_state_consume",
        lambda _state: {"redirect_url": "http://example.com", "user_id": None, "kind": "gmail"},
    )

    try:
        gmail_service.finish_gmail_oauth(code="abc", state="state123")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "user binding" in str(e).lower()


def test_finish_gmail_oauth_writes_token_per_user(monkeypatch, tmp_path):
    from app.config import settings
    from app import gmail_service

    token_dir = tmp_path / "gmail_tokens"
    token_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "token_dir", str(token_dir), raising=False)
    monkeypatch.setattr(settings, "gmail_oauth_redirect_uri", "http://localhost:8000/api/gmail/callback", raising=False)
    monkeypatch.setattr(settings, "credentials_path", "credentials.json", raising=False)

    monkeypatch.setattr(
        gmail_service,
        "oauth_state_consume",
        lambda _state: {"redirect_url": "http://example.com", "user_id": 42, "kind": "gmail"},
    )

    class DummyFlow:
        def __init__(self):
            self.credentials = {"token": "dummy"}

        def fetch_token(self, code: str):
            assert code == "abc"

    monkeypatch.setattr(
        gmail_service.InstalledAppFlow,
        "from_client_secrets_file",
        lambda *_args, **_kwargs: DummyFlow(),
    )

    redirect = gmail_service.finish_gmail_oauth(code="abc", state="state123")
    assert redirect == "http://example.com"

    token_path = token_dir / "token_42.pickle"
    assert token_path.exists()

    with token_path.open("rb") as f:
        obj = pickle.load(f)
    assert obj == {"token": "dummy"}


def test_get_gmail_service_requires_user_id_when_token_dir_set(monkeypatch, tmp_path):
    from app.config import settings
    from app import gmail_service

    token_dir = tmp_path / "gmail_tokens"
    monkeypatch.setattr(settings, "token_dir", str(token_dir), raising=False)

    try:
        gmail_service.get_gmail_service(user_id=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "user_id" in str(e).lower()

