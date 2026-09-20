# HypeCheck — implementation handoff

Last updated: September 19, 2026.

## Workspace and history

- Work in `/Users/rayanmalki/dev/htn-2026`. The project was initially created in the wrong directory, then moved here at the user's request.
- The destination repository's Git metadata and `.gitattributes` were preserved. Configuration, local data, and artifacts were moved; the Python virtual environment was recreated for this path.
- Docker Compose was restarted using the existing persistent volumes. `http://localhost/healthz` returned `{"status":"ok"}` after relocation.
- Implementation commit: `4994ca7` — `Implement HypeCheck first iteration` (60 files). This handoff file was written afterward.

## Product scope

HypeCheck analyzes spoken medical claims in public Instagram Reels and displays evidence-backed verdicts. Judges will choose videos: do not restrict inputs to preset Reel URLs or hard-coded medical topics.

Iteration one supports English videos up to 60 seconds, up to three central spoken medical claims, and a video upload fallback capped at 100 MB. The 90-second end-to-end latency is a target, not a verified guarantee. Download support depends on Instagram availability; arbitrary videos outside these constraints are not promised.

No accounts, private Instagram login, personalized treatment recommendations, response-video generation, or Instagram publishing are in scope.

## What was implemented

- **Infrastructure:** Docker Compose with Caddy, FastAPI, PostgreSQL, Redis, Celery workers, and Celery beat. Only the web proxy exposes public ports. Persistent volumes hold database, queue, and media data.
- **API:** case creation, upload fallback, case status/results, reconnectable persisted SSE events, health/readiness checks, and replay exports. Submission rate and active-case limits bound load.
- **Media intake:** Instagram URL validation, private-network destination protection, bounded `yt-dlp` downloads, upload validation, FFprobe duration checks, and FFmpeg audio extraction.
- **Model adapters:** interchangeable mock and Gemini implementations for structured transcription/claim extraction and evidence judgment. Mock output is explicitly labeled. Saved mock analysis cannot silently become live analysis when configuration changes.
- **Literature:** live Europe PMC discovery, abstracts and available open-access full text, publication deduplication, caching, retraction filtering, and stored passages with source metadata and offsets. Discovery uses neutral, title-focused, and study-type search tiers.
- **Retrieval:** shared Elasticsearch passage index, candidate-document filters, BM25 plus Elastic semantic retrieval with reciprocal rank fusion, per-paper diversity limits, and explicitly labeled keyword degradation. Live Elastic access remains unverified.
- **Verdicts:** supports, contradicts, or uncertain, with validated passage references and verbatim quotations. Technical failures produce analysis incomplete and preserve available evidence. No numerical truth score is shown.
- **Reliability:** persisted progress/checkpoints, bounded requests, task leases and abandoned-job recovery, deadlines, concurrent claim research, and media cleanup after 24 hours.
- **Observability:** frontend/backend/Celery Sentry instrumentation, trace propagation, stage timing and operational metrics, sensitive-payload scrubbing, controlled failure injection, heartbeat support, and dashboard provisioning tooling.
- **Interface:** responsive submission and case pages, progress/elapsed time, upload fallback, verdicts, expandable evidence with exact highlights, source/access labels, and an operational dashboard.
- **Replay:** versioned result data and standalone HTML export for clearly labeled offline viewing.
- **Delivery tooling:** locked dependencies, CI, deployment instructions, benchmark/smoke scripts, retrieval evaluation scaffold, and verification documentation.

## Verification already performed

These are recorded results from implementation, not a claim that tests run automatically on every later edit:

- 57 backend tests passed.
- Eight Playwright browser tests passed across desktop and mobile viewports.
- TypeScript/Vite production build passed; frontend production dependency audit reported zero known vulnerabilities at that time.
- Docker Compose configuration validated, images built, and the full local stack started.
- Real Europe PMC search and open-access full-text retrieval succeeded. Poorly focused broad matches led to discovery query refinements; no hand-reviewed retrieval accuracy score has been established.
- A real queued API case exercised blocked download → upload → FFmpeg → mock transcription → real Europe PMC. It correctly ended incomplete because Elasticsearch was unconfigured. This was not a successful live medical analysis.
- The container-served page opened in Chrome without browser errors. Exported replay rendered with browser networking disabled.
- In-memory Sentry trace tests verified timing metadata and sensitive-payload exclusion; remote Sentry ingestion has not been verified.
- After relocation, the backend imported from the new directory and the restarted API health check passed.

See `docs/VERIFICATION.md` for the detailed test record. Its mention of three demo Reels is an acceptance sample, not an input allowlist; the user clarified that judges choose the video.

## Remaining work and external dependencies

At the last configuration check, the local app used `MODEL_MODE=mock`; Gemini, Elasticsearch, and Sentry service credentials were not configured. Never print or commit secret values.

1. Configure and validate Gemini access/billing, Elasticsearch index and inference access, and Sentry ingestion.
2. Run real video → real transcript → real literature/retrieval → sourced live verdict end to end. This is required before claiming the implementation milestone is complete.
3. Hand-review retrieval queries and expected sources, compare keyword and hybrid top-five results, and retain failure examples. `evaluation/queries.json` is a scaffold, not a completed evaluation.
4. Exercise judge-selected videos and benchmark five fresh runs, reporting cached runs separately. Verify quotations and source links manually.
5. Validate external-service failures, worker restart/recovery, SSE reconnects, and three simultaneous submissions against the deployed stack.
6. Demonstrate a distributed trace in Sentry, controlled failure recovery, and one real Sentry-derived finding. Configure external uptime monitoring and alert routing.
7. Deploy to the intended Vultr VM, configure public DNS/HTTPS, and test phone access and offline rehearsal. No public deployment has been completed.

Do not present mock tests, local health checks, or replay results as proof of these live acceptance gates.

## Useful commands and files

Run commands from the repository root unless stated otherwise:

```sh
# Start local HTTP stack, preserving the explicit Compose project name hypecheck.
DOMAIN=:80 docker compose up -d
curl --fail http://localhost/healthz

# Backend tests; the explicit import path avoids local editable-install issues.
PYTHONPATH="$PWD/backend" .venv/bin/python -m pytest backend

# Frontend commands.
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

- `README.md`: setup, usage, and architecture.
- `docs/DEPLOYMENT.md`: deployment and dependency setup.
- `docs/OBSERVABILITY.md`: Sentry setup and demonstrations.
- `scripts/`: environment initialization, deployment, Sentry setup, benchmarking, and stack smoke checks.
- `backend/app/`: API, storage, queue, media, models, research, retrieval, pipeline, observability, and replay.
- `frontend/src/`: React interface and API client.

Keep `.env`, `.venv`, `node_modules`, build outputs, caches, local media/data, and artifacts out of Git. Commit source, tests, lockfiles, documentation, and `.env.example`. Preserve existing data volumes when restarting the stack; `docker compose down -v` deletes them.

## Multi-source follow-up

The multi-source branch adds supplemental MedlinePlus health topics, balanced Europe PMC candidate selection, study-design prioritization for full-text downloads, explicit provider metadata, and exact-passage Elasticsearch filters. The default index is now `hypecheck-passages-v2`; existing `.env` overrides are not automatically migrated. Run index provisioning before using a newly selected index.

Review fixes make Europe PMC mandatory for a verdict, preserve discovered source references on its failure, disclose supplemental-provider outages, and cap MedlinePlus at five seconds including retry and semaphore wait. The React interface supports health-summary labels, MedlinePlus source links, per-provider queries, source counts, and incomplete-research messages. These changes do not establish live medical accuracy or the 90-second target.

## Backboard provider follow-up

The team has Backboard credits rather than Google credits. `MODEL_PROVIDER=backboard` is now the default live route, using `BACKBOARD_API_KEY`, `BACKBOARD_LLM_PROVIDER=openai`, and `BACKBOARD_MODEL=gpt-4o-mini`. Mock mode remains the default until live credentials are configured. `backend/app/backboard.py` sends ten-second audio windows to Backboard's Whisper STT with three concurrent requests, then extracts claims with validated window references. Timestamps are explicitly coarse window ranges. Judgment shares the evidence-only prompt and citation validation with Gemini; no direct Google/OpenAI key is needed by the Backboard adapter. Readiness and preflight are provider-aware. Live STT/credit coverage and the 90-second target still need account-backed verification; do not infer them from mocked contract tests. The direct Gemini adapter remains selectable.

Live Backboard checks authenticated and found the text model, but actual chat and STT were rejected because the account credits are restricted to Memory & RAG. The key is stored only in ignored `.env`; mock mode remains enabled. Current verification: 76 backend tests, 12 browser tests, frontend production build, and CI-configured Ruff checks passed.

## Current provider: direct OpenAI

The user chose a direct OpenAI key after evaluating Backboard. `MODEL_PROVIDER=openai` is now the default; local `.env` uses `MODEL_MODE=live`. The key is stored only in ignored `.env`. `backend/app/openai_models.py` uses Whisper `verbose_json` segment timestamps and `gpt-4.1-mini` Responses structured output with `store=false`. Claim timestamps come from validated segment indices. Backboard and Gemini remain optional and are not used on this path. Provider-aware preflight performs a small real text request. Changing providers/models mid-case is rejected when saved analysis has a different model identity.

Real OpenAI text inference and transcription/claim extraction succeeded on a short synthetic spoken clip (approximately 4.35 and 5.42 seconds respectively). These timings are not an end-to-end benchmark. All 86 backend tests and lint passed; the production Docker stack rebuilt and restarted in live mode. Health is OK; readiness correctly reports Elasticsearch and its semantic endpoint missing. The 12 browser checks passed during the preceding provider integration; no further frontend changes were needed for the direct OpenAI adapter.

## Elasticsearch now connected

Local Elastic credentials are in ignored `.env`; index `hypecheck-passages-v2` and `.elser-2-elastic` are provisioned/validated. All `/readyz` dependency checks now pass. A real pipeline run on a short synthetic uploaded video completed in 14.48 seconds with hybrid retrieval, six passages, and two validated citations; 10 of 15 papers were cached. See `docs/VERIFICATION.md` for limitations. Fixed a live `_mget` request-format bug and added regression assertions. Sentry configuration, real Reel acceptance benchmarks, medical review, and public deployment still remain.

## YouTube Shorts support

Added HTTPS `/shorts/<11-character-id>` input for youtube.com, www.youtube.com and m.youtube.com,
canonicalized to www.youtube.com without tracking. UI accepts both platforms. Downloader permits
Instagram and Youtube extractors, retains public-only DNS checks and the 15-second timeout,
and supports separate video/audio tracks with local FFmpeg merging. Docker adds Node 22;
Python locks yt-dlp-ejs 0.8.0 alongside yt-dlp 2026.8.19. A real upstream Shorts test URL
BGQWPY4IigY downloaded and merged on the host. This is download verification, not a medical accuracy benchmark.
Docker/API verification also passed: case 661c5f50-4d70-4347-a21f-ca1a6e021bfc downloaded
in 3.054 seconds and finished as no_claims in 7.689 seconds using real OpenAI analysis.
102 backend tests, 14 browser checks (12 existing + 2 Shorts), lint and production build passed.

## Duration limit raised to 100 seconds

User requested a 100-second maximum. Download filtering, FFprobe validation, FFmpeg audio extraction,
transcript/claim timestamp schemas, OpenAI/Backboard adapters, API config, UI and README now use 100 seconds.
The processing target remains 90 seconds; it is not guaranteed. Added boundary tests for 97, 100,
and over-100-second media and timestamps. Earlier notes referring to 60 seconds are historical.

## Video generation is now in scope

The user explicitly expanded scope to a complete vertical narrated fact-check video and asked
for an implementation/test loop until working. This supersedes the original rendering deferral.
Added app/video.py: deterministic portrait cards from validated verdicts, OpenAI TTS, FFmpeg
MP4 assembly, captions, source manifest, checkpointed scenes, bounded concurrent synthesis/encoding.
API exposes video/captions/sources and retry; UI has rendering progress, playback/download and retry.
Only complete live medical analyses render; no-claims and mock outputs do not become medical videos.
Worker/recovery time bounds were extended for rendering; media still expires after 24h.
The previous live judgment failure was exact-quotation validation. Models now select quote IDs
from a dynamically constrained catalog; citations are copied from original stored passages and
still pass the original strict validation. No fuzzy quote matching or fabricated fallback verdicts.
Latest verification: 112 backend tests, 16 browser tests, production builds and lint passed.
Real submitted Short 15HxwdW4W0U produced narrated H.264/AAC portrait video in 66.09s wall time
(partially cached research). Mobile Chrome playback verified. Visual review prompted shorter
wording and removal of internal quotation IDs; original failed case is being retried with this refinement.
The refined original case d3ed6a35-e800-486e-b8e1-bf0317218d8e is now complete with video v2
(190.617 seconds, 11 scenes, 18 exact citations). Retry took 27.42s using saved research.
Final video frames and real mobile browser playback were verified. Artifacts are in ignored
artifacts/video-demo; source changes remain local unless subsequently committed/pushed.
