"""Unit tests for classification parsing and cache hits."""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, ClassificationCache, Application
from app.email_classifier import content_hash, _normalize_category, _regex_salary, _regex_job_title, normalize_company_name
from app.services.classification_service import get_cached_classification, classify_and_cache


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_content_hash_deterministic():
    h1 = content_hash("Subj", "from@x.com", "body")
    h2 = content_hash("Subj", "from@x.com", "body")
    assert h1 == h2
    assert len(h1) == 64
    assert content_hash("Other", "a", "b") != h1


def test_normalize_category():
    assert _normalize_category("REJECTION") == "REJECTION"
    assert _normalize_category("  interview request  ") == "INTERVIEW_REQUEST"
    assert _normalize_category("unknown") == "OTHER"


def test_regex_salary():
    min_s, max_s = _regex_salary("Salary: $80,000 - $120,000 per year")
    assert min_s == 80000
    assert max_s == 120000
    min_s, max_s = _regex_salary("$80k-$120k")
    assert min_s == 80000
    assert max_s == 120000


def test_regex_job_title():
    t = _regex_job_title("Position: Software Engineer at Acme", "")
    assert t is not None
    assert "Software" in (t or "")


def test_normalize_company_name():
    assert normalize_company_name("Acme Inc.") != "Acme Inc."
    assert "Inc" not in normalize_company_name("Acme Inc.")
    assert normalize_company_name("Unknown") == "Unknown"


def test_get_cached_classification_miss(db):
    assert get_cached_classification(db, "Subj", "from@x.com", "body") is None


def test_cache_hit_after_insert(db):
    h = content_hash("S", "F", "B")
    db.add(ClassificationCache(
        content_hash=h,
        category="REJECTION",
        company_name="Acme",
        raw_json="{}",
    ))
    db.commit()
    cached = get_cached_classification(db, "S", "F", "B")
    assert cached is not None
    assert cached["category"] == "REJECTION"
    assert cached["company_name"] == "Acme"
