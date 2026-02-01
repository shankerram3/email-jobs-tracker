"""Analytics API: funnel, response-rate, time-to-event, success prediction."""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Funnel: Applied → Interview → Offer (and Rejection branch)."""
    total = await db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == current_user.id)
    )
    total = int(total or 0)
    applied = total
    interviews = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(
            Application.user_id == current_user.id,
            Application.application_stage.in_(["Interview", "Screening"]),
        )
    )
    offers = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == current_user.id, Application.application_stage == "Offer")
    )
    rejections = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == current_user.id, Application.application_stage == "Rejected")
    )
    interviews = int(interviews or 0)
    offers = int(offers or 0)
    rejections = int(rejections or 0)

    funnel = [
        FunnelStage(stage="Applied", count=applied, pct=100.0 if total else 0),
        FunnelStage(stage="Interview / screening", count=interviews, pct=round(100.0 * interviews / total, 1) if total else 0),
        FunnelStage(stage="Offer", count=offers, pct=round(100.0 * offers / total, 1) if total else 0),
        FunnelStage(stage="Rejection", count=rejections, pct=round(100.0 * rejections / total, 1) if total else 0),
    ]
    return FunnelResponse(funnel=funnel, total=total)


@router.get("/response-rate", response_model=ResponseRateResponse)
async def get_response_rate(
    group_by: str = Query("company", description="company or industry"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Response rate by company or by industry (industry = category for now)."""
    responded_stage = ["Screening", "Interview", "Offer", "Rejected"]
    if group_by == "industry":
        # Use category as industry proxy
        rows_r = await db.execute(
            select(Application.category, func.count(Application.id).label("cnt"))
            .where(Application.user_id == current_user.id)
            .group_by(Application.category)
        )
        rows = list(rows_r.all())
        applied = {category: int(cnt or 0) for category, cnt in rows}

        responded_r = await db.execute(
            select(Application.category, func.count(Application.id).label("cnt"))
            .where(
                Application.user_id == current_user.id,
                Application.application_stage.in_(responded_stage),
            )
            .group_by(Application.category)
        )
        responded = list(responded_r.all())
        responded_d = {category: int(cnt or 0) for category, cnt in responded}
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
        applied_r = await db.execute(
            select(Application.company_name, func.count(Application.id).label("cnt"))
            .where(Application.user_id == current_user.id)
            .group_by(Application.company_name)
        )
        applied = list(applied_r.all())
        responded_r = await db.execute(
            select(Application.company_name, func.count(Application.id).label("cnt"))
            .where(
                Application.user_id == current_user.id,
                Application.application_stage.in_(responded_stage),
            )
            .group_by(Application.company_name)
        )
        responded = list(responded_r.all())
        applied_d = {name: int(cnt or 0) for name, cnt in applied}
        responded_d = {name: int(cnt or 0) for name, cnt in responded}
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
async def get_time_to_event(
    event: str = Query("rejection", description="rejection or interview"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Median and average days from received_date to event (rejection or interview)."""
    if event == "rejection":
        rows_r = await db.execute(
            select(Application.received_date, Application.rejected_at)
            .where(
                Application.user_id == current_user.id,
                Application.rejected_at.isnot(None),
            )
        )
    else:
        rows_r = await db.execute(
            select(Application.received_date, Application.interview_at)
            .where(
                Application.user_id == current_user.id,
                Application.interview_at.isnot(None),
            )
        )
    rows = list(rows_r.all())
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


async def _run_prediction_model(db: AsyncSession, user_id: int, limit: int) -> List[tuple]:
    """Simple logistic regression MVP: features = category one-hot, days_since_received; target = has_offer (or interview)."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
        import numpy as np
    except ImportError:
        return []

    rows_r = await db.execute(
        select(Application)
        .where(Application.user_id == user_id, Application.received_date.isnot(None))
        .order_by(Application.received_date.desc())
        .limit(500)
    )
    rows = list(rows_r.scalars().all())
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
    y = np.array(
        [
            1
            if (r.application_stage == "Offer")
            else (1 if (r.application_stage in ("Interview", "Screening")) else 0)
            for r in rows
        ]
    )
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
async def get_prediction(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Success prediction (basic logistic regression MVP). Returns application_id, company_name, probability.
    Requires scikit-learn; returns 503 if not installed."""
    results = await _run_prediction_model(db, current_user.id, limit)
    if results is None:
        raise HTTPException(
            status_code=503,
            detail="Prediction model unavailable. Install scikit-learn.",
        )
    items = [
        PredictionItem(application_id=aid, company_name=name, probability=round(p, 4), features=feat)
        for aid, name, p, feat in results
    ]
    return PredictionResponse(items=items, limit=limit)
