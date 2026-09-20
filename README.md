# MedBot (HypeCheck)

Public short video → spoken health claims → medical literature → cited findings → a narrated explanation.

MedBot is the current React interface for the HypeCheck backend. It checks up to **three spoken medical claims** in an **English video up to 100 seconds**, with a **100 MB upload fallback** when downloading is blocked. Supported inputs are public Instagram Reels, YouTube Shorts, and `youtu.be` share links. Inputs are not restricted to preset demo videos.

The default live provider is OpenAI. Configuration defaults to **mock mode**, which is visibly labeled: prepared claims and judgments are not an assessment of the submitted video. Literature retrieval and Elasticsearch still use real services in mock mode. The 90-second end-to-end goal is a target, not a guarantee.

## What the app provides

### Frontend

The active app is in [`frontend/`](frontend/), built with React 19, TypeScript, Vite, and local Manrope fonts.

- Responsive link submission, scanner progress, elapsed time, and upload fallback. Saved cases reopen through `?case=<id>`; an encoded `?url=<video-url>` starts a new check automatically.
- Persisted server-sent events reconnect to saved progress and ignore stale updates. Failed analyses can resume through the retry action.
- Claim cards with supported, contradicted, uncertain, or incomplete findings; expandable original wording, full assessments, limitations, and transcript.
- An evidence drawer and source catalog with exact quotations, original links, retrieval ranks, and **full text / abstract only / health summary** labels. Per-paper match details and findings appear when saved in the result. Rank measures relevance, not study quality or truth.
- A captioned video viewer in an accessible dialog, with generation progress, readiness notification, and expired-media handling. MP4, caption, and source downloads are available through the API.
- Optional GPTZero document probabilities, confidence, and sentence signals, kept separate from medical findings. The hallucination-check display says **Not run**; no hallucination-detection integration is enabled.
- Native sharing with clipboard/manual-link fallbacks, plus an offline HTML copy of the written findings. Dialogs support Escape and focus return; animations respect reduced-motion preferences.

The current interface does not expose the former Observatory dashboard. Operational aggregates remain available at `/api/metrics`. There are no accounts: anyone with a case link can view it. Avoid submitting sensitive personal medical information. Findings are a limited research assessment, not diagnosis or treatment advice.

### Backend and evidence

FastAPI serves cases, uploads, saved progress, findings, and artifacts. Celery workers run analysis and rendering; PostgreSQL stores cases/events, Redis handles the queue and leases, and Celery Beat schedules recovery, cleanup, and health check-ins. Docker Compose serves the frontend and API through Caddy; only the web proxy publishes ports.

1. **Intake:** validate supported URLs, reject private-network destinations, download with `yt-dlp`, and validate duration/audio with FFprobe. Failed downloads can resume with an uploaded file. YouTube watch pages, playlists, and arbitrary hosts are rejected; supported share links normalize to Shorts URLs.
2. **Transcription and claims:** the OpenAI adapter uses `whisper-1` segment timestamps and `gpt-4.1-mini` structured extraction. Claim timestamps reference validated transcript segments. Optional claim details capture stated population, intervention, formulation, outcome, comparator, dose, and timeframe. Unspoken details stay unset.
3. **Discovery:** Europe PMC supplies papers, abstracts, and available open-access full text. Up to 15 deduplicated papers and five full texts are considered per claim. Optional MedlinePlus health summaries supplement the research. Missing full text remains labeled abstract-only; summaries are not presented as studies. Known retractions are excluded and paper retrieval is cached for 24 hours.
4. **Retrieval:** Elasticsearch indexes traceable passages with source/access metadata and exact offsets. BM25 keyword search and ELSER semantic search combine through reciprocal rank fusion, restricted to the current claim's discovered candidates. Results contain at most six passages and two per paper. Semantic failure can produce an explicitly labeled keyword-only result; total retrieval failure remains an incomplete analysis.
5. **Assessment:** the shared judgment contract produces `supports`, `contradicts`, or `uncertain`, with per-paper applicability, findings, and limitations. Citation IDs resolve to stored quotations, and validation rejects unknown, inexact, cross-paper, or known-retracted citations. Citation validation does not establish that the model interpreted the study correctly. Provider or validation failures preserve evidence and mark the analysis incomplete.

Optional Elastic reranking uses an **existing** inference endpoint and defaults off. A failed or invalid rerank preserves the original ranking. See [Elastic architecture and measured limitations](docs/ELASTIC.md); the recorded benchmark does not demonstrate a relevance improvement from reranking.

GPTZero, when configured, checks authorship patterns in the transcript. Its results never enter medical judgment, and detector failures do not fail the analysis. `GPTZERO_FILLER_READING=true` enables an experimental second reading with speech fillers removed and an additional API call.

### Generated videos

One staged renderer serves automatic generation, manual generation, and retries through Celery and `result.video`:

`script → voice → cards → compose → post → captions`

Complete live analyses can produce a **45–120-second, 720×1280, 30 fps H.264/AAC video** about one claim: the earliest contradicted claim, otherwise the earliest assessed claim. Other findings remain in the app. Mock, no-claim, incomplete, or invalid-citation analyses cannot produce medical videos.

The video uses a short original claim excerpt when suitable source media is available; otherwise it uses a labeled claim card. It preserves the saved verdict and limitations and shows reproduced source excerpts, not screenshots of journal pages. OpenAI supplies disclosed AI narration (`TTS_MODEL=gpt-4o-mini-tts`, `TTS_VOICE=coral`). Local whisper.cpp aligns generated speech; invalid alignment falls back to disclosed estimated caption timing. Narration failures are explicit. Essential speech that cannot fit 120 seconds fails with `script_budget_exceeded` rather than being truncated.

Renderer version 4 overlaps narration and card layout, reuses integrity-checked scene/audio checkpoints, and combines transitions, captions, sound, and optional split-screen in the final encode. Sound effects default on; split-screen (`brainrot`) defaults off. `VIDEO_ENABLED=false` disables automatic rendering; manual requests still require eligible live findings. Video failures preserve the findings and allow retry.

Analysis has a configurable 120-second default deadline. **Rendering currently has no overall deadline, and Celery soft/hard task limits are disabled.** Individual provider calls and alignment have bounded waits. Worker leases renew while jobs run; recovery checks abandoned cases after six minutes when no processing lease remains. Inactive media is cleaned up after 24 hours; active jobs are excluded. Download videos separately from the written offline replay.

See [renderer operation](backend/app/video/VIDEO.md) for tools, cache behavior, CLI rendering, and benchmarks. Existing version-2 artifacts remain readable; legacy `result.render` records must be regenerated. Social publishing and experimental resolver, paper-scanner, and crawler tools are not integrated into this pipeline.

## Start the full stack

Use Docker with the Compose plugin. The backend image includes Python 3.13, Node 22, FFmpeg/FFprobe, local fonts, pinned Playwright/Chromium, and pinned whisper.cpp with its alignment model. The first build downloads these dependencies.

Run from the repository root:

```sh
# First setup only; an existing .env is left unchanged.
python scripts/init_env.py
# Edit .env with the external configuration below, then:
docker compose up -d --build
# Once Elasticsearch credentials and inference access are configured:
docker compose exec -T api python -m app.cli setup-elastic
docker compose exec -T api python -m app.cli preflight
```

The equivalent Bash startup helper is `bash scripts/start.sh`: it builds/starts the services, runs Elastic setup when credentials are present, and always runs preflight. Mock mode does not bypass missing database, Redis, or Elastic requirements.

Open **https://localhost** with the default `DOMAIN=localhost`. Local Caddy certificates need local trust or a browser exception. Set `DOMAIN=:80` in `.env` for local HTTP at **http://localhost**, or set a public DNS name for a public HTTPS deployment. `scripts/init_env.py` creates random local secrets and host-development addresses; Compose overrides database, Redis, and media addresses for its containers.

### External configuration

Keep credentials in ignored `.env` or environment variables. See [`.env.example`](.env.example) for the complete configuration.

| Setting | Purpose |
|---|---|
| `MODEL_MODE=live`, `MODEL_PROVIDER=openai`, `OPENAI_API_KEY` | Enable real transcription, claim extraction, and judgment; the same key supplies video narration |
| `OPENAI_MODEL` | Text model, default `gpt-4.1-mini` |
| `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY` | Server-side Elasticsearch endpoint and API key |
| `ELASTIC_INDEX`, `ELASTIC_INFERENCE_ID` | Default passage index `hypecheck-passages-v2` and semantic endpoint `.elser-2-elastic` |
| `ELASTIC_SEMANTIC` | Default `true`; `false` explicitly selects keyword-only retrieval |
| `ELASTIC_RERANK_ENABLED`, `ELASTIC_RERANK_INFERENCE_ID`, `ELASTIC_RERANK_TIMEOUT_SECONDS` | Optional reranking; disabled by default, using an existing endpoint and a timeout of at most three seconds |
| `MEDLINEPLUS_ENABLED` | Supplemental health summaries, default `true`; Europe PMC remains required |
| `VIDEO_ENABLED`, `TTS_MODEL`, `TTS_VOICE` | Automatic live video generation and narration settings |
| `WHISPER_MODEL` | Local narration-alignment model path; built into the Docker image |
| `GPTZERO_API_KEY` | Optional transcript authorship detection; skipped when unset |
| `SENTRY_DSN`, `VITE_SENTRY_DSN` | Optional Python/backend and React/frontend Sentry projects |
| `SENTRY_*_SAMPLE_RATE`, `VITE_SENTRY_*_SAMPLE_RATE` | Trace, profile, and error-Replay sampling; see [observability](docs/OBSERVABILITY.md) |
| `DOMAIN` | Caddy hostname or local HTTP binding |

Europe PMC and MedlinePlus require no API key in this implementation. `setup-elastic` validates semantic inference and creates the configured passage index; configure an available inference ID if the default is unavailable. It does not provision an optional reranking endpoint.

Preflight checks database/Redis, Elastic index/inference access, the selected live model, optional GPTZero access, and renderer dependencies when automatic live video is enabled. Live OpenAI preflight makes a small billed text request; it does not verify transcription or narration. `sentry_configured` only reports that a DSN is set, not successful ingestion.

Gemini and Backboard remain optional analysis adapters: set `MODEL_PROVIDER=gemini` with `GEMINI_API_KEY`/`GEMINI_MODEL`, or `MODEL_PROVIDER=backboard` with `BACKBOARD_API_KEY`/`BACKBOARD_LLM_PROVIDER`/`BACKBOARD_MODEL`. Video narration still requires OpenAI. Provider access and billing must be verified for the selected account.

After changing `.env`, rerun `docker compose up -d --build` to recreate services and rebuild frontend configuration; `docker compose restart` does not reload environment values. API keys and Sentry auth tokens must never enter frontend configuration. A browser Sentry DSN is public by design. Preserve existing volumes: `docker compose down -v` deletes persistent data.

## Local development

Use Python 3.13 to match CI, Node 22+, and the locked dependencies. Native API/worker development also needs a reachable Redis service. The initializer uses SQLite for host development; Compose uses PostgreSQL. Keep commands at the repository root unless shown otherwise.

### Python environment

macOS/Linux:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install -e './backend[dev]'
export PYTHONPATH="$PWD/backend"
.venv/bin/python -m app.cli init-db
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Create/configure `.env` with the initializer first if it does not exist. These commands invoke the environment directly; activation is optional. Use Docker or a Linux/WSL environment for the complete worker and renderer on Windows.

In separate macOS/Linux terminals with Redis running and the same configuration:

```sh
.venv/bin/celery -A app.queue.celery worker --loglevel=INFO --concurrency=2
.venv/bin/celery -A app.queue.celery beat --loglevel=INFO --schedule=data/celerybeat-schedule
```

For native media work, both `ffmpeg` and `ffprobe` must be on `PATH`. On Windows, add their executable directory and reopen the terminal, then check `ffmpeg -version` and `ffprobe -version`. Installing Python dependencies does not install them.

Host rendering also needs local fonts, whisper.cpp's `whisper-cli` and alignment model, plus the browser toolchain:

```sh
npm ci --prefix backend/app/video
node backend/app/video/node_modules/playwright/cli.js install chromium
```

Set `WHISPER_MODEL` to the host model path; [the Dockerfile](backend/Dockerfile) records the pinned runtime and model revisions. Linux browser installations may also need Playwright's `--with-deps` option. Set `VIDEO_ENABLED=false` for analysis-only development without the rendering toolchain.

### Frontend development

```sh
npm ci --prefix frontend
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api`, `/healthz`, and `/readyz` to the host API at `127.0.0.1:8000`. Compose does not publish that API port, so these defaults require the native API above. For frontend-only fixture tests, a running backend is not needed.

Native Vite reads `VITE_SENTRY_*` settings from the frontend environment, for example ignored `frontend/.env.local`; the root `.env` supplies these values to the Docker build. Set `UPTIME_URL=http://127.0.0.1:8000/healthz` for a host worker.

## API

| Route | Result |
|---|---|
| `GET /api/config` | Public model mode, semantic-search setting, duration limit, and timing target |
| `POST /api/cases` with `{"source_url":"https://www.instagram.com/reel/.../"}` | 202, queued case snapshot |
| `POST /api/cases/{id}/media` with multipart `file` | Resume a case waiting for video upload |
| `GET /api/cases/{id}` | Saved state, findings, provenance, timings, video status, and sequence |
| `GET /api/cases/{id}/events` | Reconnectable SSE with persisted sequence IDs |
| `POST /api/cases/{id}/retry` | Resume saved analysis or rendering work |
| `POST /api/cases/{id}/render?brainrot=false&sfx=true` | Queue eligible live findings through the same renderer |
| `GET /api/cases/{id}/video` | Stream MP4 with Range support; `?download=true` downloads it |
| `GET /api/cases/{id}/video/captions` | WebVTT captions |
| `GET /api/cases/{id}/video/sources` | Script/source manifest with exact quotes and limitations |
| `GET /api/cases/{id}/replay?format=html` | Standalone offline written findings; `format=json` returns recording data |
| `GET /api/metrics` | Aggregate case counts and timings from the last 24 hours |
| `GET /healthz`, `GET /readyz` | Process health and dependency readiness |
| `POST /api/admin/failure` | Controlled Sentry error, gated by feature flag and administrator bearer token |

The native backend exposes OpenAPI at **http://127.0.0.1:8000/docs**. Caddy's public proxy routes `/api/*` and health endpoints, not `/docs`.

## Observability

Elasticsearch retrieves evidence; Sentry diagnoses application failures and performance. Backend instrumentation covers FastAPI/Celery errors, pipeline traces, sampled profiles, and structured operational logs. Frontend instrumentation covers React errors, browser traces/profiles, and error-only Session Replay with text/inputs masked and media blocked.

Beat sends a health check-in every minute. An external Sentry Uptime Monitor must be configured separately to check public DNS, TLS, and API reachability. Optional Gemini AI spans capture usage metadata; default OpenAI work appears in pipeline spans rather than dedicated token/usage spans. Sentry MCP is an optional operator connection, not part of the app's request path. See [Sentry configuration and verification](docs/OBSERVABILITY.md).

## Verification

Run from the repository root after installing dependencies:

```sh
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check --config ruff.toml backend scripts
npm --prefix frontend run build
# Install Chrome for the frontend Playwright configuration if it is unavailable:
cd frontend
npx playwright install chrome
npm test
cd ..
```

PowerShell backend equivalents:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m ruff check --config ruff.toml backend scripts
```

Frontend Playwright tests cover desktop/mobile submission, uploads, SSE recovery, evidence, authorship states, video UI, and sharing with intercepted responses. They do not establish live provider accuracy or actual media playback. Backend media integration tests require their external executables; review reported skips. Cue-timing tests run without FFmpeg. `.pytest-tmp-*/`, caches, generated media, and test artifacts are ignored.

CI also builds the production renderer image and exercises its video tests with networking disabled. For existing results and their limitations, see [backend/render verification](docs/VERIFICATION.md), [MedBot integration](docs/MEDBOT-UI-VERIFICATION.md), and [UI refinement checks](docs/UI-REFRESH-VERIFICATION.md). Recorded checks describe their stated checkout and fixtures; they do not certify your current credentials, data, or deployment.

For retrieval evaluation and a live-link benchmark:

```sh
.venv/bin/python -m app.cli evaluate evaluation/queries.json
.venv/bin/python scripts/benchmark.py --base-url https://YOUR_DOMAIN demo-links.json
```

`demo-links.json` is a JSON array of public video URLs. Review original papers and fill `expected_paper_ids` before claiming retrieval quality; unlabeled rows remain `unreviewed`. Compare actual retrieval modes and report cache use. [Elastic notes](docs/ELASTIC.md) describe the separate optional-rerank benchmark; `scripts/benchmark_video.py` measures rendering from saved analysis, not a fresh end-to-end check.

After starting a reachable deployment, the Bash helper can exercise a chosen Short and save its generated artifacts:

```sh
BASE_URL=https://YOUR_DOMAIN bash scripts/e2e_short.sh 'https://www.youtube.com/shorts/VIDEO_ID'
```

Use `BASE_URL=http://localhost` for `DOMAIN=:80`, or a trusted HTTPS origin. This helper requires live analysis and a ready video; its polling window is about three minutes, so longer renders may outlast it. A blocked download, mock result, or incomplete analysis is not a successful live run.

Public deployment, representative fresh-video trials, hand-reviewed evidence, real Sentry ingestion, failure recovery, and concurrent-run latency still need verification for the intended environment. See [deployment](docs/DEPLOYMENT.md) and the [sponsor demo guide](docs/SPONSOR-DEMO.md). Historical handoffs are in [docs/HANDOFF-HISTORY.md](docs/HANDOFF-HISTORY.md).
