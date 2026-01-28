"""Classification with cache: hash lookup, LLM on miss, persist and normalize company."""
import json
from sqlalchemy.orm import Session

from ..models import ClassificationCache, Company
from ..email_classifier import (
    content_hash,
    structured_classify_email,
    normalize_company_name,
)


def get_cached_classification(db: Session, subject: str, sender: str, body: str) -> dict | None:
    """Return structured payload if cache hit, else None."""
    h = content_hash(subject, sender, body)
    row = db.query(ClassificationCache).filter(ClassificationCache.content_hash == h).first()
    if not row:
        return None
    return {
        "category": row.category,
        "subcategory": row.subcategory,
        "company_name": row.company_name or "Unknown",
        "job_title": row.job_title,
        "salary_min": row.salary_min,
        "salary_max": row.salary_max,
        "location": row.location,
        "confidence": row.confidence,
    }


def classify_and_cache(
    db: Session,
    subject: str,
    sender: str,
    body: str,
) -> dict:
    """
    Classify email: check cache first; on miss call LLM, persist to cache, normalize company.
    Returns structured payload (category, subcategory, company_name, job_title, salary_*, location, confidence).
    """
    h = content_hash(subject, sender, body)
    cached = get_cached_classification(db, subject, sender, body)
    if cached is not None:
        company = normalize_company_with_db(db, cached["company_name"])
        cached["company_name"] = company
        return cached

    result = structured_classify_email(subject, body, sender)
    company = normalize_company_with_db(db, result["company_name"])
    result["company_name"] = company

    raw_json = json.dumps({
        "category": result["category"],
        "subcategory": result.get("subcategory"),
        "company_name": result["company_name"],
        "job_title": result.get("job_title"),
        "salary_min": result.get("salary_min"),
        "salary_max": result.get("salary_max"),
        "location": result.get("location"),
        "confidence": result.get("confidence"),
    })
    row = ClassificationCache(
        content_hash=h,
        category=result["category"],
        subcategory=result.get("subcategory"),
        company_name=result["company_name"],
        job_title=result.get("job_title"),
        salary_min=result.get("salary_min"),
        salary_max=result.get("salary_max"),
        location=result.get("location"),
        confidence=result.get("confidence"),
        raw_json=raw_json,
    )
    db.add(row)
    db.commit()
    return result


def normalize_company_with_db(db: Session, name: str) -> str:
    """Canonicalize company name: strip suffixes; if companies table has match, return canonical."""
    normalized = normalize_company_name(name)
    company = db.query(Company).filter(Company.canonical_name == normalized).first()
    if company:
        return company.canonical_name
    company = db.query(Company).filter(Company.aliases.isnot(None)).all()
    for c in company:
        aliases = c.aliases or []
        if isinstance(aliases, str):
            try:
                import json
                aliases = json.loads(aliases) if aliases else []
            except Exception:
                aliases = []
        if normalized in aliases or name in aliases:
            return c.canonical_name
    return normalized
