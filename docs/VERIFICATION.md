# Verification record

## What is automated

- Backend contracts: URL validation, private destination rejection, citation/offset validation, study filtering, abstract/full-text resolution, cache behavior, hybrid-query filters, keyword degradation, upload limits, event cursor replay, queue admission, concurrency, worker checkpoints, and HTML replay escaping.
- Real local FFmpeg/FFprobe processes are exercised with a generated one-second audio/video fixture.
- Browser tests on desktop and mobile cover the landing page, form/API error, completed evidence, verbatim highlighting, source link, upload fallback, and metrics. Test responses are fixtures and do not assert medical truth.
- Docker configuration and image builds are checked separately from remote deployment.

## Live services exercised

- Europe PMC search and open-access full-text retrieval were reached successfully during implementation. An initial vitamin C/common-cold query returned 15 candidate papers and 228 passages, 214 from full text. Several high-ranked broad matches were poorly focused; title-focused and study-type discovery tiers were added in response. These counts are a connectivity observation, not a retrieval accuracy score.
- A live MedlinePlus health-topic query for `common cold` returned five normalized sources and 12 passages. Provider failure isolation and source normalization are also covered by backend tests; this connectivity check is not a medical relevance evaluation.
- The Docker stack built and started successfully: Caddy, FastAPI, PostgreSQL, Redis, Celery workers, and beat. PostgreSQL/Redis readiness checks passed; Elastic readiness correctly failed without credentials.
- A real API submission and queued Celery job attempted an unavailable Reel, offered upload, accepted a generated two-second video, extracted audio with FFmpeg, used the explicitly mocked transcript, and queried real Europe PMC. It terminated as `incomplete` when Elastic was unconfigured. This verifies infrastructure failure behavior, not medical inference.

## Latest local test results

- 86 backend tests passed, including an in-memory Sentry trace capture proving stage timings and metadata are serialized without sensitive payloads, and a hard-deadline test that ensures unfinished claims never masquerade as completed judgments.
- Twelve browser tests passed across desktop and mobile viewports; production TypeScript/Vite build succeeded.
- Frontend production dependency audit reported zero known vulnerabilities.
- Deployment Compose configuration validated and all container images built.
- The actual container-served page was opened in Chrome with no browser errors. A downloaded replay was opened with browser networking disabled; its recorded results rendered successfully without network resources.

## Pending external acceptance gates

- Hosted Elasticsearch index, inference entitlement, real hybrid search, and judged retrieval evaluation.
- Gemini account/billing access, real transcription, and evidence-grounded medical judgment.
- Team's three demo Reels and five measured live runs, with cached/fresh results separated.
- Sentry ingestion, distributed trace in its UI, real incident/improvement record, external uptime monitor, and alert routing.
- Vultr deployment, public DNS/TLS, phone access over venue Wi-Fi, and physical offline rehearsal.

Required secrets and VM/domain details were not available at implementation start. Mock tests and local screenshots must not be presented as having passed these live gates.

## Multi-source review verification

- Required Europe PMC outages fail research even if MedlinePlus returns zero or nonzero results; pipeline tests verify no judgment is called and discovered source references remain available.
- A stalled MedlinePlus request is cancelled at its separate deadline while primary evidence remains usable; supplemental failure is included in verdict limitations.
- Desktop and mobile browser tests verify health-summary labels, MedlinePlus citation links, source counts, provider-outage messages, and incomplete retrieval display.
- Production frontend build and CI-configured Ruff checks passed. These checks use controlled fixtures and do not replace live service acceptance or retrieval-quality evaluation.

## Backboard integration and live access check

The Backboard API key authenticated, the billing endpoint reported a positive balance, and the configured text model appeared in the catalog. Actual text inference returned `FAILED`, and speech transcription returned HTTP 400: the account's current credits are reserved for Memory & RAG and cannot fund either operation. No live transcript or verdict was produced. The local application remains in mock mode. Redeem applicable sponsor credits or resolve the entitlement with Backboard before enabling live mode; do not assume the displayed balance covers model calls.

The adapter uses Backboard HTTP requests with memory/web search disabled, validates JSON and citation references, and derives coarse timestamps from fixed audio windows rather than generated timestamps. Preflight now probes actual text inference to detect restricted credits.

## Direct OpenAI switch

The user selected direct OpenAI. The key authenticated for real Responses inference and Whisper audio transcription. A short synthetic spoken clip produced timestamped transcript segments and an extracted claim; text and audio/claim checks took about 4.35 and 5.42 seconds. This is a provider smoke test, not a medical accuracy evaluation or Reel benchmark. Local mode is now live and the Docker stack has been rebuilt. `/healthz` passes; `/readyz` reports database, Redis, and model configuration ready, with Elasticsearch and semantic inference still unavailable. All 86 backend tests and CI-configured Ruff checks passed.

## Elasticsearch live integration

Elastic credentials were configured in ignored `.env`. Elasticsearch 9.5.4 and `.elser-2-elastic` were reachable, and `hypecheck-passages-v2` was provisioned. Preflight passed database, Redis, index, inference endpoint, and real OpenAI text-inference checks. `/readyz` now reports ready.

The first synthetic spoken-video run exposed an invalid `_mget` request: source filtering was in the JSON body instead of a query parameter. The request was corrected to use `_source_includes`, with regression assertions. All 13 research tests and focused Ruff checks passed.

A subsequent generated short video completed through the real upload/FFmpeg/OpenAI/Europe PMC/Elasticsearch/judgment path in 14.48 seconds wall time. Case: `4f65abb6-6986-4ee4-a3a5-a208f3cd810e`. It discovered 15 papers, reused 10 cached papers, indexed 246 passages (zero index-cache hits), and returned six passages using hybrid retrieval with two validated quotations. Both quotations were checked against stored passage text and context. Research took 3.66 seconds and judgment 4.895 seconds. The failed download used an intentionally nonexistent fixture Reel URL followed by automatic upload.

This is a synthetic, short-video integration check with partially cached literature. It is not a fresh judge-selected Reel benchmark, full medical review, or evidence that all 60-second videos finish under 90 seconds. Local artifacts are in `artifacts/elastic-smoke/` and remain ignored.

## YouTube Shorts — September 19, 2026

- Added strict Shorts URL validation, both-platform UI, YouTube extractor, pinned EJS 0.8.0 and Node 22 in Docker, and separate-stream merging.
- 102 backend tests passed; 12 existing browser checks and two new desktop/mobile Shorts submission checks passed. Ruff and production Docker/frontend builds passed.
- Real Short `https://www.youtube.com/shorts/BGQWPY4IigY` downloaded through the rebuilt API/Celery stack with no upload fallback. Case `661c5f50-4d70-4347-a21f-ca1a6e021bfc` returned `no_claims` without errors.
- Download 3.054 seconds; audio extraction 0.167; real transcription/claim extraction 4.330; total processing 7.689 seconds. Clip duration approximately 14 seconds, audio and video present.
- This verifies Shorts intake and real model processing, not medical retrieval accuracy or the five-run latency acceptance target. Other videos may encounter YouTube restrictions.

## 100-second limit and user Short

Duration limit raised at user request across intake, extraction, adapters, timestamp schemas, API and UI.
Existing 102 backend tests passed, plus four new duration/timestamp boundary cases passed in focused tests;
lint and rebuilt production images passed. `/api/config` reports max_duration_seconds=100.
Retried `15HxwdW4W0U` as case `d3ed6a35-e800-486e-b8e1-bf0317218d8e`: duration 96.901s,
download 4.238s, transcription 7.945s, total 26.952s. Download and research succeeded;
all three judgments ended incomplete with `Evidence judgment failed validation or timed out.`
This is not a successful end-to-end medical verdict and requires separate judgment diagnosis.

## Narrated video generation — September 19, 2026

The user expanded scope to vertical narrated fact-check videos. Diagnosed the previous failures by
re-running judgment against saved evidence: generated quotes were not verbatim. The model now
selects quotation IDs constrained by a per-request JSON-schema enum; original source slices are
copied into citations and checked with the unchanged validator. Invalid IDs and quotes still fail.

Added deterministic portrait cards, OpenAI gpt-4o-mini-tts narration, FFmpeg assembly, downloadable
H.264/AAC MP4, approximate WebVTT captions, source/script manifest, retry and cached scene recovery.
The voice is disclosed as AI-generated in the video and app. Incomplete or mock judgments cannot
produce a medical response video. Source titles are abbreviated visually when needed; full titles,
URLs and exact quotations remain in the manifest and evidence view.

- 112 backend tests passed, including real FFmpeg rendering, HTTP Range delivery, cache reuse,
  quotation validation, render failure preserving verdicts, retry, expiry and path checks.
- 16 browser checks passed across desktop/mobile; production build, Docker rebuild and Ruff passed.
- Fresh case submission of the user's 97-second Short: `44e16a6a-acb4-4218-a386-1e03c0bd2158`.
  Actual download, transcription, research, judgment, TTS and rendering completed in 66.09 seconds
  wall time (65.611 processing). Rendering took 42.937 seconds. Literature/index caches were partially
  reused (paper cache hits 2/6/1 across claims); this is NOT a fully cold benchmark.
- Verified output: 720×1280 H.264 + AAC, approximately 12.2 MB. Actual mobile Chrome playback advanced
  beyond one second, had no media error, and the page had no horizontal overflow.
- Visual review found internal quotation markers and overly long wording in the first render.
  Tightened judgment wording, removed standalone internal ID groups, and retained source citations
  and limitations. A second run retries the user's originally failed case with the revised renderer.

No five-run speed guarantee, independent medical review, or public hosting verification is implied.

Final refined output: original case `d3ed6a35-e800-486e-b8e1-bf0317218d8e` recovered through the
public retry endpoint and completed in 27.42 seconds wall time using its saved research/transcript.
Version 2 output is 190.617 seconds long with 11 scenes and 18 citations, all rechecked as exact
substrings in stored passage text/context. No internal quotation IDs remain in narration.
Final frame visually inspected; final MP4 played successfully in mobile Chrome with no media error.
Local deliverable: `artifacts/video-demo/hypecheck-final.mp4`, with result/source JSON and screenshots
beside it (ignored by Git). Output duration differs from the 100-second input-video limit.
