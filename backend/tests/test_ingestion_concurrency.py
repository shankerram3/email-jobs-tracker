import pytest
from sqlalchemy.exc import OperationalError


def test_chunk_list_splits_evenly():
    from app.services import email_processor as ep

    items = list(range(10))
    chunks = ep._chunk_list(items, 3)
    assert chunks == [list(range(0, 3)), list(range(3, 6)), list(range(6, 9)), [9]]


def test_commit_with_retry_retries_on_sqlite_lock():
    from app.services import email_processor as ep

    class DummyDB:
        def __init__(self):
            self.commit_calls = 0
            self.rollback_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls < 3:
                # Mimic sqlite lock error surfaced via SQLAlchemy OperationalError
                raise OperationalError("COMMIT", {}, Exception("database is locked"))

        def rollback(self):
            self.rollback_calls += 1

    db = DummyDB()
    ep._commit_with_retry(db, max_retries=5, base_sleep_s=0.0)
    assert db.commit_calls == 3
    assert db.rollback_calls == 2

