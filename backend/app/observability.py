from contextlib import contextmanager
from time import monotonic

import sentry_sdk
from sentry_sdk import logger as sentry_logger

from app.config import settings

SAFE_LOG_ATTRIBUTES = {
    "case_id", "case_status", "duration_seconds", "model_mode", "provider", "stage",
}


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


def scrub_log(log, hint):
    """Allow only technical correlation fields on deliberately static log messages."""
    attributes = log.get("attributes", {})
    log["attributes"] = {
        key: value for key, value in attributes.items()
        if key in SAFE_LOG_ATTRIBUTES or key.startswith("sentry.")
    }
    return log


def log_event(message: str, **attributes):
    """Emit a structured Sentry log without accepting medical or model payload fields."""
    safe = {key: value for key, value in attributes.items() if key in SAFE_LOG_ATTRIBUTES}
    sentry_logger.info(message, attributes=safe)


def record_case_duration(seconds: float):
    """Attach total case time to the transaction, even inside a child span."""
    transaction = sentry_sdk.get_current_scope().transaction
    if transaction is not None:
        transaction.set_data("case.duration_seconds", seconds)


def configure_sentry():
    cfg = settings()
    if not cfg.sentry_dsn:
        return
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    sentry_sdk.init(
        dsn=cfg.sentry_dsn, environment=cfg.sentry_environment, release=cfg.release,
        integrations=[FastApiIntegration(), CeleryIntegration()],
        traces_sample_rate=cfg.sentry_traces_sample_rate,
        profile_session_sample_rate=cfg.sentry_profile_session_sample_rate,
        profile_lifecycle="trace",
        enable_logs=cfg.sentry_enable_logs,
        send_default_pii=False, include_local_variables=False,
        max_request_body_size="never", before_send=scrub, before_send_transaction=scrub,
        before_send_log=scrub_log,
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
