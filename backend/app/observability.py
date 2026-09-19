from contextlib import contextmanager
from time import monotonic

import sentry_sdk

from app.config import settings


def scrub(event, hint):
    # Keep operation names, numerical measurements and case IDs, never payloads.
    event.pop("request", None)
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    for value in event.get("exception", {}).get("values", []):
        value["value"] = value.get("type", "Error")
        for frame in value.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    for span in event.get("spans", []):
        if span.get("op", "").startswith(("http", "db", "queue")):
            span["description"] = span.get("op", "external")
            span["data"] = {}
    return event


def configure_sentry():
    cfg = settings()
    if not cfg.sentry_dsn:
        return
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    sentry_sdk.init(
        dsn=cfg.sentry_dsn, environment=cfg.sentry_environment, release=cfg.release,
        integrations=[FastApiIntegration(), CeleryIntegration()],
        traces_sample_rate=1.0, send_default_pii=False, include_local_variables=False,
        max_request_body_size="never", before_send=scrub, before_send_transaction=scrub,
    )


@contextmanager
def stage(name: str, timings: dict):
    start = monotonic()
    with sentry_sdk.start_span(op=f"pipeline.{name}", name=name) as span:
        try:
            yield span
        except BaseException:
            span.set_status("internal_error")
            raise
        finally:
            elapsed = round(monotonic() - start, 3)
            timings[name] = timings.get(name, 0) + elapsed
            span.set_data("duration_seconds", elapsed)
