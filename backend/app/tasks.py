import asyncio
import shutil
from datetime import timedelta

import httpx
import sentry_sdk
from sqlalchemy import select

from app.config import settings
from app.db import Case, now, session
from app.pipeline import run_case
from app.queue import celery, enqueue, redis_client


@celery.task(name="app.tasks.process_case")
def process_case(case_id: str):
    lock = redis_client().lock(f"processing:{case_id}", timeout=170, blocking=False)
    if not lock.acquire(blocking=False):
        return
    try:
        asyncio.run(run_case(case_id))
    finally:
        try:
            lock.release()
        except Exception:
            pass


@celery.task(name="app.tasks.recover")
def recover():
    # Database cases act as an outbox if API-to-broker dispatch or a worker fails.
    with session() as db:
        pending = db.scalars(select(Case).where(
            Case.status.in_(["queued", "downloading", "transcribing", "researching", "judging"]),
            Case.updated_at < now() - timedelta(seconds=180),
        )).all()
        for case in pending:
            if not redis_client().exists(f"processing:{case.id}"):
                enqueue(case.id)


@celery.task(name="app.tasks.cleanup")
def cleanup():
    from app.db import update_case
    with session() as db:
        expired = db.scalars(select(Case).where(Case.updated_at < now() - timedelta(hours=24))).all()
        for case in expired:
            if case.status in {"queued", "downloading", "transcribing", "researching", "judging"}:
                continue
            folder = settings().media_root / case.id
            if folder.exists():
                shutil.rmtree(folder)
            if case.media_path:
                update_case(case.id, media_path=None)


@celery.task(name="app.tasks.uptime")
@sentry_sdk.monitor(monitor_slug="hypecheck-api-uptime", monitor_config={
    "schedule": {"type": "crontab", "value": "* * * * *"},
    "checkin_margin": 2, "max_runtime": 1, "timezone": "UTC",
    "failure_issue_threshold": 1, "recovery_threshold": 1,
})
def uptime():
    # Missing check-ins also expose a dead VM/beat process, unlike an unmonitored local probe.
    response = httpx.get(settings().uptime_url, timeout=10)
    response.raise_for_status()
