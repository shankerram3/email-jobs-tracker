"""Analytics API: funnel, response-rate, time-to-event, success prediction."""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Application, User
from ..schemas import (
    FunnelResponse,
    FunnelStage,
    ResponseRateResponse,
    ResponseRateItem,
    TimeToEventResponse,
    PredictionResponse,
    PredictionItem,
)
from ..auth import get_current_user_required

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _app_query(db: Session, user: User):
    return db.query(Application).filter(Application.user_id == user.id)


@router.get("/funnel", response_model=FunnelResponse)
def get_funnel(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Funnel: Applied → Interview → Offer (and Rejection branch)."""
    q = _app_query(db, current_user)
    total = q.count()
    applied = total
    interviews = q.filter(Application.category.in_(["INTERVIEW_REQUEST", "ASSESSMENT"])).count()
    offers = q.filter(Application.category == "OFFER").count()
    rejections = q.filter(Application.category == "REJECTION").count()

    funnel = [
        FunnelStage(stage="Applied", count=applied, pct=100.0 if total else 0),
        FunnelStage(stage="Interview", count=interviews, pct=round(100.0 * interviews / total, 1) if total else 0),
        FunnelStage(stage="Offer", count=offers, pct=round(100.0 * offers / total, 1) if total else 0),
        FunnelStage(stage="Rejection", count=rejections, pct=round(100.0 * rejections / total, 1) if total else 0),
    ]
    return FunnelResponse(funnel=funnel, total=total)


@router.get("/response-rate", response_model=ResponseRateResponse)
def get_response_rate(
    group_by: str = Query("company", description="company or industry"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Response rate by company or by industry (industry = category for now)."""
    q = _app_query(db, current_user)
    if group_by == "industry":
        # Use category as industry proxy
        rows = (
            q.with_entities(Application.category, func.count(Application.id).label("cnt"))
            .group_by(Application.category)
            .all()
        )
        applied = {r.category: r.cnt for r in rows}
        responded = (
            q.filter(Application.category.in_(["REJECTION", "INTERVIEW_REQUEST", "ASSESSMENT", "OFFER"]))
            .with_entities(Application.category, func.count(Application.id).label("cnt"))
            .group_by(Application.category)
            .all()
        )
        responded_d = {r.category: r.cnt for r in responded}
        items = [
            ResponseRateItem(
                name=cat,
                applied=applied.get(cat, 0),
                responded=responded_d.get(cat, 0),
                rate=round(responded_d.get(cat, 0) / applied[cat], 2) if applied.get(cat) else 0,
            )
            for cat in (applied.keys() or ["OTHER"])
        ]
    else:
        # By company
        applied = (
            q.with_entities(Application.company_name, func.count(Application.id).label("cnt"))
            .group_by(Application.company_name)
            .all()
        )
        responded = (
            q.filter(Application.category.in_(["REJECTION", "INTERVIEW_REQUEST", "ASSESSMENT", "OFFER"]))
            .with_entities(Application.company_name, func.count(Application.id).label("cnt"))
            .group_by(Application.company_name)
            .all()
        )
        applied_d = {r.company_name: r.cnt for r in applied}
        responded_d = {r.company_name: r.cnt for r in responded}
        items = [
            ResponseRateItem(
                name=name,
                applied=applied_d[name],
                responded=responded_d.get(name, 0),
                rate=round(responded_d.get(name, 0) / applied_d[name], 2),
            )
            for name in applied_d
        ]
        items = sorted(items, key=lambda x: -x.applied)[:50]
    return ResponseRateResponse(group_by=group_by, items=items)


def _days_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end:
        return None
    if start.tzinfo:
        start = start.replace(tzinfo=None)
    if end.tzinfo:
        end = end.replace(tzinfo=None)
    delta = end - start
    return delta.total_seconds() / (24 * 3600)


@router.get("/time-to-event", response_model=TimeToEventResponse)
def get_time_to_event(
    event: str = Query("rejection", description="rejection or interview"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Median and average days from received_date to event (rejection or interview)."""
    q = _app_query(db, current_user)
    if event == "rejection":
        rows = (
            q.with_entities(Application.received_date, Application.rejected_at)
            .filter(Application.rejected_at.isnot(None))
            .all()
        )
    else:
        rows = (
            q.with_entities(Application.received_date, Application.interview_at)
            .filter(Application.interview_at.isnot(None))
            .all()
        )
    days_list = []
    for r in rows:
        d = _days_between(r.received_date, r.rejected_at if event == "rejection" else r.interview_at)
        if d is not None:
            days_list.append(d)
    if not days_list:
        return TimeToEventResponse(event=event, median_days=None, avg_days=None, sample_size=0)
    days_list.sort()
    n = len(days_list)
    median = days_list[n // 2] if n % 2 else (days_list[n // 2 - 1] + days_list[n // 2]) / 2
    avg = sum(days_list) / n
    return TimeToEventResponse(
        event=event,
        median_days=round(median, 1),
        avg_days=round(avg, 1),
        sample_size=n,
    )


def _run_prediction_model(db: Session, user_id: int, limit: int) -> List[tuple]:
    """Simple logistic regression MVP: features = category one-hot, days_since_received; target = has_offer (or interview)."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
        import numpy as np
    except ImportError:
        return []

    rows = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.received_date.isnot(None))
        .order_by(Application.received_date.desc())
        .limit(500)
        .all()
    )
    if len(rows) < 10:
        return []

    le = LabelEncoder()
    categories = [r.category or "OTHER" for r in rows]
    le.fit(categories)
    X = []
    for r in rows:
        days = (datetime.utcnow() - (r.received_date or datetime.utcnow())).total_seconds() / (24 * 3600)
        cat_enc = le.transform([r.category or "OTHER"])[0]
        X.append([days, cat_enc])
    X = np.array(X)
    y = np.array([1 if r.category == "OFFER" else (1 if r.category in ("INTERVIEW_REQUEST", "ASSESSMENT") else 0) for r in rows])
    if y.sum() < 2:
        return []
    clf = LogisticRegression(max_iter=500, random_state=42)
    clf.fit(X, y)
    probs = clf.predict_proba(X)[:, 1]
    out = []
    for i, r in enumerate(rows[:limit]):
        out.append((r.id, r.company_name or "Unknown", float(probs[i]), {"days_since_received": X[i][0], "category_enc": int(X[i][1])}))
    return out


@router.get("/prediction", response_model=PredictionResponse)
def get_prediction(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Success prediction (basic logistic regression MVP). Returns application_id, company_name, probability."""
    results = _run_prediction_model(db, current_user.id, limit)
    items = [
        PredictionItem(application_id=aid, company_name=name, probability=round(p, 4), features=feat)
        for aid, name, p, feat in results
    ]
    return PredictionResponse(items=items, limit=limit)
