"""Celery app for async email sync. Uses Redis; DB session per task."""
from celery import Celery
from .config import settings

celery_app = Celery(
    "job_tracker",
    broker=settings.celery_broker,
    backend=settings.redis_url,
    include=["app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
