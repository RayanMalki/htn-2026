# HypeCheck

Instagram Reel / YouTube Short → spoken claims → medical literature → Elasticsearch passages → cited verdicts.

Iteration one is implemented as a FastAPI/Celery backend, PostgreSQL/Redis persistence, a React/Vite interface, and a Docker Compose deployment with Caddy HTTPS. OpenAI is the default live provider for transcription, claim extraction, and judgment; the direct Gemini adapter remains optional. Model mode defaults to **mock**; a mock verdict is never presented as a real medical assessment. Europe PMC, MedlinePlus, and Elasticsearch are real services even in mock model mode.

## Start here

```bash
python3 scripts/init_env.py
# Edit .env: add Elasticsearch credentials and Sentry DSNs.
# Keep MODEL_MODE=mock until OpenAI credentials are available.
docker compose up -d --build
docker compose exec api python -m app.cli setup-elastic
docker compose exec api python -m app.cli preflight
```

Open **https://localhost**. Local Caddy certificates may need trust or a browser exception. For a public deployment, set `DOMAIN` to a real DNS name pointed to the VM; Caddy obtains the public certificate automatically. `DOMAIN=:80` enables plain HTTP for local development only.

The repository includes `.env.example`; `scripts/init_env.py` creates an ignored `.env` with random local secrets. It never overwrites an existing file. Compose overrides database/Redis/media addresses for containers. Do not paste API keys into the frontend or commit `.env`.

**Required external configuration**

| Setting | Purpose |
|---|---|
| `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY` | Hosted Elasticsearch endpoint and server-side API key |
| `ELASTIC_INFERENCE_ID` | Existing Elastic inference endpoint; defaults to `.elser-2-elastic` |
| `SENTRY_DSN`, `VITE_SENTRY_DSN` | Backend and frontend Sentry project DSNs; frontend DSN is public by design |
| `SENTRY_*_SAMPLE_RATE`, `VITE_SENTRY_*_SAMPLE_RATE` | Trace, profile, and masked error-Replay sampling; see `docs/OBSERVABILITY.md` |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `MODEL_MODE=live` | Enable real video transcription and evidence judgment |
| `OPENAI_API_KEY`, `MODEL_PROVIDER=openai`, `MODEL_MODE=live` | Direct OpenAI transcription and evidence judgment |
| `OPENAI_MODEL` | Text model; defaults to `gpt-4.1-mini` |
| `DOMAIN` | Public DNS name for Caddy HTTPS |

`setup-elastic` validates the inference endpoint and creates the passage index. If your deployment does not provide the default inference ID, enable an Elastic-managed endpoint in Elastic Cloud and configure its ID. `ELASTIC_SEMANTIC=false` explicitly selects keyword-only retrieval; it is not equivalent to the intended hybrid demo. Never silently replace a failed search with a mock search.

After changing environment values, run `docker compose up -d --build` (use `DOMAIN=:80` for local HTTP). Updating frontend DSNs requires rebuilding the web image.

The default direct OpenAI adapter transcribes the complete clip using `whisper-1` with segment timestamps, then uses `gpt-4.1-mini` for structured claim extraction and evidence judgment. Claim time ranges are derived from validated transcript segment references, not generated timestamps. Responses requests use `store=false`, no tools, and no conversation history. Citation validation remains mandatory. See [OpenAI transcription](https://developers.openai.com/api/docs/guides/speech-to-text) and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Preflight makes a small billed text-inference request; a live audio test is still needed to verify transcription access. The 90-second end-to-end target remains unverified.

Optional adapters remain available: `MODEL_PROVIDER=gemini` uses `GEMINI_API_KEY`; `MODEL_PROVIDER=backboard` uses `BACKBOARD_API_KEY`, `BACKBOARD_LLM_PROVIDER`, and `BACKBOARD_MODEL`. Backboard's tested paid text/voice calls were blocked by Memory & RAG-only credits, although some explicit OpenRouter free text models worked. Its transcription adapter uses coarse ten-second windows. Neither alternative is used by the default OpenAI path.

## Local development

Requires Python 3.12+, Node 22+, FFmpeg/FFprobe, and Redis. SQLite is supported for local API tests; the deployment uses PostgreSQL.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
.venv/bin/pip install -e './backend[dev]'
export PYTHONPATH="$PWD/backend"
.venv/bin/python -m app.cli init-db
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# In another terminal, with a local Redis server running:
.venv/bin/celery -A app.queue.celery worker --loglevel=INFO --concurrency=2
# In another terminal:
.venv/bin/celery -A app.queue.celery beat --loglevel=INFO --schedule=data/celerybeat-schedule
# Frontend:
cd frontend
npm ci
npm run dev
```

Use http://127.0.0.1:5173. Vite proxies `/api` to FastAPI. For a local worker, set `UPTIME_URL=http://127.0.0.1:8000/healthz`.

## Behavior

- Public Instagram Reel or YouTube Shorts URLs, English speech, up to 100 seconds, up to three claims. Clips without usable audio/medical claims receive an explicit outcome.
- Video downloads time out after 15 seconds. A blocked download offers a 100 MB video upload into the same case. File validity/duration/audio are checked by FFprobe; private-network redirects are rejected in the isolated downloader.
- Search reserves candidates for title matches, reviews/meta-analyses/trials, and broader literature through Europe PMC. Up to 15 deduplicated papers and five relevance-prioritized open-access full texts per claim are considered. MedlinePlus adds up to five curated health-topic summaries with a five-second deadline, including retries and queue wait. Its failure is disclosed in the interface and verdict limitations. Europe PMC is required: an outage marks research incomplete and preserves discovered source references. Known retracted publications are excluded; this is not a complete retraction registry.
- Exact stored-source passages go into a shared Elasticsearch index. BM25 and semantic queries are fused with RRF and filtered to the exact passages discovered for the current claim. Results are capped at six passages and two passages per source. A failed semantic operation may fall back to keyword search, explicitly labeled in the result.
- Conclusions are `supports`, `contradicts`, or `uncertain`, with validated verbatim citations. Service errors or invalid citations produce `incomplete`, not `uncertain`. Results are bounded research assessments, not treatment advice.
- Events are committed to PostgreSQL before a Redis notification is published. SSE replays persisted events using `Last-Event-ID`; its one-second database poll remains usable if notifications are missed.
- Celery jobs are acknowledged after processing. A Redis lease prevents duplicate execution; persisted checkpoints reuse transcription and completed claim research after interruption. Beat recovers abandoned cases after three minutes.
- PostgreSQL holds the versioned case result and event history. Temporary source video/audio are deleted after 24 hours; standalone HTML and JSON replay artifacts remain available separately.
- The 90-second goal includes queue wait, excludes human upload time, and is measured separately from cached-paper runs. A hard 120-second worker pipeline deadline preserves partial results. Three simultaneous requests receive case IDs immediately; the third can wait for one of two workers.

## API

| Route | Result |
|---|---|
| `POST /api/cases` with `{"source_url":"https://www.instagram.com/reel/.../"}` | 202, queued case snapshot |
| `POST /api/cases/{id}/media` multipart field `file` | Resume an `awaiting_upload` case |
| `GET /api/cases/{id}` | Versioned result, status, timings, error, and event sequence |
| `GET /api/cases/{id}/events` | SSE `case` events; `end` event closes completed streams |
| `GET /api/cases/{id}/replay?format=html` | Download a standalone offline replay; `format=json` returns recording data |
| `GET /api/metrics` | Aggregate counts and stage durations over the last 24 hours |
| `GET /healthz`, `GET /readyz` | Process health and dependency readiness |
| `POST /api/admin/failure` | Controlled Sentry error; requires feature flag and administrator bearer token |

Inspect OpenAPI at the backend's `/docs` in development. No accounts are required for the demo; case URLs are bearer-style unlisted links, not private records. Avoid submitting sensitive personal medical information.

## Verification

```bash
.venv/bin/pytest backend/tests -q
.venv/bin/ruff check --config ruff.toml backend scripts
cd frontend
npm run build
npm test
```

Browser tests use installed Google Chrome and intercept external responses. They verify the UI contract on desktop and mobile, **not model accuracy or a live Elastic deployment**. Backend tests cover security boundaries, real FFmpeg, citation rejection, failure behavior, event replay, caching, concurrency, and restart checkpoints.

Retrieval evaluation:

```bash
.venv/bin/python -m app.cli evaluate evaluation/queries.json
```

Review the returned original papers and fill `expected_paper_ids` in the dataset before claiming retrieval quality. Rows with no reviewed labels remain `unreviewed` and have a null score. Inspect `actual_mode` before comparing hybrid with keyword search. No quality improvement is assumed.

For five live links in a JSON array:

```bash
.venv/bin/python scripts/benchmark.py --base-url https://YOUR_DOMAIN demo-links.json
```

This records wall time, cache use, model mode, and failures. A blocked Instagram link is reported as `awaiting_upload`, never as a successful fast run. Download completed HTML replays before the demo; they use no network resources.

## Operations and remaining live gates

See [deployment](docs/DEPLOYMENT.md), [observability](docs/OBSERVABILITY.md), and [verification record](docs/VERIFICATION.md).

Live completion requires a provisioned VM/domain, hosted Elastic inference access, Gemini credentials, Sentry project access, and the team's three chosen demo Reel URLs. Until those gates are exercised, do not claim a hosted 90-second automated medical fact-checker is verified.

### YouTube Shorts

Submit `https://www.youtube.com/shorts/VIDEO_ID` (mobile YouTube URLs also work).
The same English-speech, 100-second and 100 MB limits apply. Tracking parameters are removed;
watch pages, playlists and arbitrary hosts are rejected. Docker includes Node 22 and the pinned
`yt-dlp-ejs` solver package. Downloads can merge separate video/audio tracks using FFmpeg.
For development outside Docker, install Node 22+ in addition to the locked Python requirements.
YouTube access restrictions can still trigger upload fallback; no cookies or paid downloader are required by the integration.

### Generated fact-check videos

Successful live analyses automatically produce a 720×1280 narrated MP4. The script uses the
validated claim, verdict, explanation and limitations directly; it does not invent a second
medical summary. Evidence is cited on cards and linked in the downloadable source manifest,
including exact quotations. Narration is disclosed as AI-generated. Captions use approximate
sentence timing. Videos are independent fact-check cards, not edits of the original speaker.

`OPENAI_API_KEY` also funds narration (`TTS_MODEL=gpt-4o-mini-tts`, `TTS_VOICE=coral`).
`VIDEO_ENABLED=false` disables automatic rendering. Mock/no-claim/incomplete analyses do not
produce medical videos. The 90-second target now includes rendering for enabled live cases;
rendering has its own bounded 150-second deadline, and exceeding the target is disclosed.
The Celery job limit is 310 seconds, processing lease 330 seconds, recovery threshold 360 seconds.

- `GET /api/cases/{id}/video`: playable MP4 with HTTP Range support; add `?download=true` to save it.
- `GET /api/cases/{id}/video/captions`: English WebVTT captions.
- `GET /api/cases/{id}/video/sources`: script, scene timing, source URLs and exact quotations.
- `POST /api/cases/{id}/retry`: resume a failed analysis/render from saved evidence and scene artifacts.

Video failures preserve completed medical findings, visibly mark the case incomplete, and offer
retry. Scene audio and encoded clips are content-versioned and reused on retry. Videos expire
with temporary media after 24 hours: download the MP4 and sources for offline use. Instagram
publishing remains outside the app.
