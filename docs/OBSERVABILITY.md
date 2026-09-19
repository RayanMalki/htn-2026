# Sentry and the pipeline observatory

## Implemented instrumentation

Backend SDK: FastAPI + Celery integrations, full demo trace sampling, release/environment tags, case ID correlation, and spans for download, audio extraction, transcription, literature, indexing, retrieval, and judgment. HTTP, database, and queue spans retain timing but remove payload details. Exceptions remove values and frame locals. Transcripts, media, model prompts, and credentials are not sent intentionally.

The browser SDK propagates traces for same-origin `/api/` requests and captures React errors. Session Replay is deliberately not enabled because its DOM could contain submitted claims and medical text. This is separate from the application's explicitly downloaded offline case replay.

The app's **Observatory** shows persisted counts, p50/p95 durations, queue size, and average stage times without requiring Sentry access. Cases in mock mode are labeled; use trace filters to separate them from live runs.

## Configure the Sentry workspace

1. Create Python/FastAPI and React projects. Set `SENTRY_DSN` and `VITE_SENTRY_DSN` and rebuild the web container.
2. Set optional `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT_ID` for dashboard provisioning; run `.venv/bin/python scripts/setup_sentry.py`. The token needs organization dashboard write access. For regional accounts, set `SENTRY_API_BASE` to the region's API origin. The script updates a same-name dashboard rather than creating duplicates.
3. Open Traces and filter `has:case_id`; choose a case to follow API enqueue → Celery → external calls. Inspect `pipeline.*` spans and numeric cache/paper counters.
4. Beat runs an SDK-monitored uptime task every minute. It requests `UPTIME_URL` (default: internal API health). With a DSN, the `hypecheck-api-uptime` cron monitor reports failures and missing check-ins if the worker, Redis, beat, or VM stops.
5. For public reachability, also create a Sentry Uptime Monitor for `https://YOUR_DOMAIN/healthz`. This external monitor must be created in the Sentry UI; the built-in cron probe alone does not verify public DNS/TLS. Use a one-minute interval where the account supports it.
6. In **Monitors & Alerts → Alerts**, create a rule for the backend project and uptime monitor: trigger on new or regressed issues, filter production errors, and route to the team's chosen existing notification destination. Also create a duration monitor for `app.tasks.process_case` above 90 seconds if your workspace supports trace-metric alerts. This account configuration requires access and is not automatically enabled by installing the SDK.

Current documentation: https://docs.sentry.io/api/dashboards/create-a-new-dashboard-for-an-organization/ and https://docs.sentry.io/product/monitors-and-alerts/alerts/.

## Controlled failure demonstration

Set `ENABLE_FAILURE_INJECTION=true` for the demonstration, then use the API with `Authorization: Bearer <ADMIN_TOKEN>` from a local tool. `POST /api/admin/failure` captures a labeled, data-free error and returns HTTP 503 and its Sentry event ID. Do not expose the token in frontend code. Turn the feature off afterward.

Record the event link and the trace showing where it happened. Recovery is demonstrated by the health endpoint and a subsequent successful case, not by pretending the deliberately failed request succeeded.

## Record a real finding

Use this template for an issue discovered through Sentry, rather than inventing an incident:

```text
Case ID and release:
Sentry issue/trace URL:
Observed failure or slow stage:
Root cause:
Change made:
Before/after measurements:
Limitations (cache state, sample count, mock/live):
```

No real Sentry finding is claimed until a connected workspace receives a real run. Local test failures or retrieval observations are useful engineering findings but are not evidence of having used Sentry in production.
