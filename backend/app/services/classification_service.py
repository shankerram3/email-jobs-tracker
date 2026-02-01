"""Classification with cache: hash lookup, LLM on miss, persist and normalize company."""
import json
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..models import ClassificationCache, Company
from ..email_classifier import (
    content_hash,
    structured_classify_email,
    normalize_company_name,
    apply_category_overrides,
)


def get_cached_classification(
    db: Session,
    subject: str,
    sender: str,
    body: str,
    user_id: int | None,
) -> dict | None:
    """Return structured payload if cache hit, else None."""
    h = content_hash(subject, sender, body)
    if user_id is None:
        return None
    row = (
        db.query(ClassificationCache)
        .filter(ClassificationCache.content_hash == h, ClassificationCache.user_id == user_id)
        .first()
    )
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
    user_id: int | None,
) -> dict:
    """
    Classify email: check cache first; on miss call LLM, persist to cache, normalize company.
    Returns structured payload (category, subcategory, company_name, job_title, salary_*, location, confidence).
    """
    h = content_hash(subject, sender, body)
    cached = get_cached_classification(db, subject, sender, body, user_id)
    if cached is not None:
        cached = apply_category_overrides(cached, subject, body, sender)
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
    if user_id is not None:
        row = ClassificationCache(
            user_id=user_id,
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
        try:
            db.commit()
        except IntegrityError:
            # Race condition: another thread inserted the same content_hash
            # Roll back and fetch the existing row
            db.rollback()
            existing = (
                db.query(ClassificationCache)
                .filter(ClassificationCache.content_hash == h, ClassificationCache.user_id == user_id)
                .first()
            )
            if existing:
                # Update the existing row with our result
                existing.category = result["category"]
                existing.subcategory = result.get("subcategory")
                existing.company_name = result["company_name"]
                existing.job_title = result.get("job_title")
                existing.salary_min = result.get("salary_min")
                existing.salary_max = result.get("salary_max")
                existing.location = result.get("location")
                existing.confidence = result.get("confidence")
                existing.raw_json = raw_json
                db.commit()
    return result


def persist_llm_result_to_cache(
    db: Session,
    subject: str,
    sender: str,
    body: str,
    result: dict,
    user_id: int | None,
    commit: bool = True,
) -> dict:
    """
    Persist an LLM classification result to cache and return result with company normalized.
    Uses upsert: update existing row by content_hash if present, else insert. Avoids
    UNIQUE constraint when the same email content is reclassified or appears in a batch twice.
    When commit=False, caller must commit.
    """
    company = normalize_company_with_db(db, result["company_name"])
    result = {**result, "company_name": company}
    h = content_hash(subject, sender, body)
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
    if user_id is None:
        return result
    existing = (
        db.query(ClassificationCache)
        .filter(ClassificationCache.content_hash == h, ClassificationCache.user_id == user_id)
        .first()
    )
    if existing:
        existing.category = result["category"]
        existing.subcategory = result.get("subcategory")
        existing.company_name = result["company_name"]
        existing.job_title = result.get("job_title")
        existing.salary_min = result.get("salary_min")
        existing.salary_max = result.get("salary_max")
        existing.location = result.get("location")
        existing.confidence = result.get("confidence")
        existing.raw_json = raw_json
    else:
        row = ClassificationCache(
            user_id=user_id,
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

    # Flush to detect constraint violations early, even when commit=False
    try:
        db.flush()
    except IntegrityError:
        # Race condition: another thread inserted between our check and flush
        db.rollback()
        # Retry: fetch and update the now-existing row
        existing = (
            db.query(ClassificationCache)
            .filter(ClassificationCache.content_hash == h, ClassificationCache.user_id == user_id)
            .first()
        )
        if existing:
            existing.category = result["category"]
            existing.subcategory = result.get("subcategory")
            existing.company_name = result["company_name"]
            existing.job_title = result.get("job_title")
            existing.salary_min = result.get("salary_min")
            existing.salary_max = result.get("salary_max")
            existing.location = result.get("location")
            existing.confidence = result.get("confidence")
            existing.raw_json = raw_json
            db.flush()

    if commit:
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
