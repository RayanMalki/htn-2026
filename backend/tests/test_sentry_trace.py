import json

import sentry_sdk
from sentry_sdk.transport import Transport

from app.observability import record_case_duration, scrub, scrub_log, stage


def test_stage_trace_captures_timing_without_sensitive_payloads():
    envelopes = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    with sentry_sdk.init(dsn="https://public@sentry.example/1", transport=Capture(),
                         traces_sample_rate=1.0, before_send=scrub, before_send_transaction=scrub,
                         include_local_variables=False, default_integrations=False):
        with sentry_sdk.start_transaction(name="app.tasks.process_case", op="queue.task"):
            sentry_sdk.set_tag("case_id", "test-case-id")
            timings = {}
            with stage("literature", timings) as span:
                span.set_data("papers_found", 15)
                record_case_duration(1.5)
        sentry_sdk.flush()
    transactions = [item.payload.json for envelope in envelopes for item in envelope.items
                    if item.headers.get("type") == "transaction"]
    assert len(transactions) == 1
    assert transactions[0]["tags"]["case_id"] == "test-case-id"
    assert transactions[0]["contexts"]["trace"]["data"]["case.duration_seconds"] == 1.5
    assert "case.duration" not in transactions[0].get("measurements", {})
    spans = transactions[0]["spans"]
    assert all("case.duration_seconds" not in span.get("data", {}) for span in spans)
    assert any(span["op"] == "pipeline.literature" and span["data"]["papers_found"] == 15 for span in spans)
    assert "transcript" not in json.dumps(transactions)


def test_case_duration_without_transaction_is_noop():
    with sentry_sdk.new_scope() as scope:
        scope.span = None
        record_case_duration(1.5)


def test_sentry_log_scrubber_keeps_only_safe_attributes():
    log = {"body": "HypeCheck case finished", "attributes": {
        "case_id": "case-1", "duration_seconds": 4.2, "claim": "sensitive medical text",
        "sentry.trace.parent_span_id": "abc",
    }}
    scrubbed = scrub_log(log, {})
    assert scrubbed["attributes"] == {
        "case_id": "case-1", "duration_seconds": 4.2, "sentry.trace.parent_span_id": "abc",
    }
    assert "sensitive" not in json.dumps(scrubbed)
