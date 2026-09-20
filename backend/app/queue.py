from functools import lru_cache

import redis
from celery import Celery

from app.config import settings
from app.observability import configure_sentry

configure_sentry()
celery = Celery("hypecheck", broker=settings().redis_url, include=["app.tasks"])
celery.conf.update(
    task_default_queue="cases", task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, task_serializer="json", accept_content=["json"],
    broker_connection_retry_on_startup=True, broker_connection_timeout=2,
    broker_transport_options={"visibility_timeout": 360},
    task_soft_time_limit=None, task_time_limit=None,
    beat_schedule={
        "recover-unfinished-cases": {"task": "app.tasks.recover", "schedule": 30.0},
        "delete-expired-media": {"task": "app.tasks.cleanup", "schedule": 3600.0},
        "uptime-check": {"task": "app.tasks.uptime", "schedule": 60.0},
    },
)


@lru_cache
def redis_client():
    return redis.Redis.from_url(settings().redis_url, socket_connect_timeout=2, socket_timeout=2,
                                 decode_responses=True)


def enqueue(case_id: str):
    celery.send_task("app.tasks.process_case", args=[case_id], retry=False)
