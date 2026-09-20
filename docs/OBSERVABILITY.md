# Sentry and the pipeline observatory

HypeCheck uses Sentry for errors, traces, profiles, structured logs, error-only browser replays, cron monitoring, external uptime monitoring, and optional Gemini request monitoring. OpenAI is the default provider; its work is visible in pipeline stage spans, but dedicated OpenAI token/usage spans are not currently implemented. The local **Observatory** remains useful when Sentry is unavailable: it shows persisted counts, p50/p95 durations, queue size, and average stage times.

## What is connected

| Sentry product | HypeCheck integration | Data policy |
|---|---|---|
| Tracing | FastAPI, Celery, browser navigation/API spans, and `pipeline.*` stages | HTTP, database, and queue payload fields are removed |
| Profiling | Python and browser profiles use trace lifecycle sampling | Sampling is configurable independently for each project |
| Logs | Explicit case-start and case-finish server logs | Only case ID, status, duration, mode, stage, and provider attributes are allowed |
| Session Replay | React error sessions only | All text and inputs are masked; all media is blocked; no selectors are unmasked |
| Uptime Monitoring | External `/healthz` monitor plus a one-minute Celery cron check-in | Health status only |
| Optional Gemini AI monitoring | Manual `gen_ai.request` spans around Gemini transcription and judgment | Model, operation, token counts, and finish reason only; no prompt, transcript, audio, evidence, or response |
| Sentry MCP | Optional operator connection from an MCP client to the Sentry workspace | This is not part of the HypeCheck request path |

Exceptions remove values and frame locals. Request bodies, user context, breadcrumbs, and arbitrary extras are also removed. Cases in mock mode are tagged so they can be separated from live runs.

## Configure the projects

Create a **Python/FastAPI** project and a **React** project in the same Sentry organization. Copy the server DSN into `SENTRY_DSN` and the browser DSN into `VITE_SENTRY_DSN`. The browser DSN is public by design; keep Sentry auth tokens server-side.

Add these values to `.env`:

```dotenv
SENTRY_DSN=https://...your-python-project-dsn...
SENTRY_ENVIRONMENT=production
SENTRY_ENABLE_LOGS=true
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_PROFILE_SESSION_SAMPLE_RATE=0.2
RELEASE=hypecheck-<git-sha>

VITE_SENTRY_DSN=https://...your-react-project-dsn...
VITE_SENTRY_ENVIRONMENT=production
VITE_SENTRY_TRACES_SAMPLE_RATE=1.0
VITE_SENTRY_PROFILE_SESSION_SAMPLE_RATE=0.1
VITE_SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE=1.0
```

Rates must be between `0` and `1`. The values above are useful for a short judged demo. Reduce trace/profile rates after measuring event volume in production. Setting a profile rate to `0` disables profiling; setting the Replay error rate to `0` disables Session Replay. Normal browser sessions are never sampled because `replaysSessionSampleRate` is fixed at zero.

Rebuild both images so Vite receives its build-time variables:

```sh
docker compose up -d --build
```

Submit a case, then check both Sentry projects:

1. In **Traces**, filter the backend project for `case_id:<id>`. Open `app.tasks.process_case` and confirm the `pipeline.download`, `pipeline.transcription`, `pipeline.literature`, `pipeline.retrieval`, and `pipeline.judgment` spans that apply to the run.
2. In **Profiles**, open a sampled backend or browser trace. Profiles only appear when both the trace and profile samplers select that session.
3. In **Logs**, filter for `case_id:<id>`. You should see the static start and finish messages with status and timing fields, without claim text.
4. In a staging browser console, run `setTimeout(() => { throw new Error("Sentry Replay verification") }, 0)`, then open **Replays**. Verify rendered text and inputs are masked and video/audio is absent before relying on the configuration.
5. Only when using the optional Gemini provider, open the trace and find `gen_ai.request`. Confirm the operation, model, finish reason, and token counts. Search the event JSON for part of the submitted claim and confirm it is absent.

Frontend-to-backend propagation is limited to same-origin `/api/` requests. A browser trace and its queued worker trace may appear as related but separate transactions because the durable Celery boundary can outlive the HTTP request.

## Uptime and cron monitoring

Celery Beat runs the SDK-monitored `app.tasks.uptime` task every minute. It requests `UPTIME_URL` and reports to the `hypecheck-api-uptime` cron monitor. Missing check-ins can detect a stopped worker, Redis failure, Beat failure, or stopped VM.

Create a separate Sentry **Uptime Monitor** for:

```text
https://YOUR_DOMAIN/healthz
```

Use a one-minute interval if the account supports it. This external request verifies public DNS, TLS, Caddy, and the API. The internal cron request defaults to `http://api:8000/healthz` in Compose and cannot prove public reachability. Route both monitors to the team's alert destination and test one alert before the demo.

## AI monitoring and Sentry MCP

The optional Gemini provider is called through a direct REST adapter, so HypeCheck creates manual `gen_ai.request` spans rather than relying on an OpenAI, Anthropic, or LangChain integration. The spans use Sentry's generative-AI attributes and record token usage returned in Gemini's `usageMetadata`. HypeCheck is a fixed pipeline, not an autonomous agent, so it does not emit misleading agent/tool/handoff spans.

Sentry MCP serves a different purpose: it lets an authorized AI coding or operations client inspect Sentry issues and traces. To use it, add the remote server `https://mcp.sentry.dev` to an MCP-capable client, start the connection, and complete Sentry's OAuth flow in the browser. Select only the HypeCheck organization and grant the least access needed. Do not add an MCP credential to `.env`; MCP is an operator connection and is not required by the deployed app.

Use MCP for questions such as “show recent production HypeCheck errors” or “find slow `pipeline.literature` spans.” Treat any action that edits or resolves Sentry issues as an operator action subject to the client's confirmation controls.

## Dashboard and alerts

Set `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, and `SENTRY_PROJECT_ID` only if you want the included dashboard provisioner, then run:

```sh
.venv/bin/python scripts/setup_sentry.py
```

The token needs organization dashboard write access. For a regional account, set `SENTRY_API_BASE` to its API origin. The script updates a same-name dashboard instead of creating duplicates.

Case duration is stored as numeric transaction data under `case.duration_seconds`, using `set_data`.
The p50/p95 widgets use the spans dataset and aggregate `tags[case.duration_seconds,number]`,
filtered to `app.tasks.process_case` transactions. Widget titles specify seconds because custom data
does not carry a measurement unit. The existing total-time calculation still includes queue wait and
prior attempts. Re-run the provisioner to update an already-created dashboard; live widget queries
must be verified after ingestion into the connected Sentry workspace.

Create alerts for new or regressed backend issues, production error volume, missed cron check-ins, and external uptime failures. If the plan supports trace-metric alerts, add one for `app.tasks.process_case` over 90 seconds. Installing the SDK does not create notification routes automatically.

## Controlled failure demonstration

Set `ENABLE_FAILURE_INJECTION=true`, then call `POST /api/admin/failure` with `Authorization: Bearer <ADMIN_TOKEN>` from a local tool. The endpoint captures a labeled, data-free error and returns HTTP 503 with its Sentry event ID. Turn the feature off afterward and verify recovery with `/healthz` plus a subsequent successful case.

Record a real Sentry finding with this template:

```text
Case ID and release:
Sentry issue/trace URL:
Observed failure or slow stage:
Root cause:
Change made:
Before/after measurements:
Limitations (cache state, sample count, mock/live):
```

No real Sentry finding is claimed until a connected workspace receives a real run.

## Sentry product showcase endpoint

For a bounded sponsor demo, set `SENTRY_DEMO_ENABLED=true` alongside the server
`SENTRY_DSN` and `ADMIN_TOKEN`, then call:

```sh
curl -i -X POST https://YOUR_DOMAIN/api/admin/sentry-demo \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The endpoint intentionally returns `503` and emits one data-free exception, warning,
structured log, trace transaction, failure span, synthetic `gen_ai.request` span, and short profiling candidate. The
JSON response includes the event IDs and trace ID to paste into Sentry. It does not
generate a browser Session Replay or a missed uptime check-in: open the React app to
exercise Replay, while the existing Celery Beat task owns the `hypecheck-api-uptime`
monitor. Keep this endpoint disabled outside a controlled demo.

Official references: [Python tracing](https://docs.sentry.io/platforms/python/tracing/), [Python logs](https://docs.sentry.io/platforms/python/logs/), [Python profiling](https://docs.sentry.io/platforms/python/profiling/), [React Session Replay](https://docs.sentry.io/platforms/javascript/guides/react/session-replay/), [React profiling](https://docs.sentry.io/platforms/javascript/guides/react/profiling/), [Uptime Monitoring](https://docs.sentry.io/product/uptime-monitoring/), and [LLM monitoring](https://docs.sentry.io/product/llm-monitoring/getting-started/).

## Staged renderer

The worker retains the `pipeline.rendering` span. `result.video.stage` records the
active stage and the manifest stores successful per-stage elapsed seconds. Rendering
runs in a cancellable subprocess; sanitized provider/budget failures are propagated
back to the case, and other internal errors use a generic retry message. No raw
provider response, narration text, local artifact path or credential is placed in a
public failure message. Use stage timings to distinguish synthesis, layout, encoding
and caption costs. `whisper` versus `estimated` caption timing is recorded explicitly.
