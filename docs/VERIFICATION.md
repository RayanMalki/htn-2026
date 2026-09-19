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

- 57 backend tests passed, including an in-memory Sentry trace capture proving stage timings and metadata are serialized without sensitive payloads, and a hard-deadline test that ensures unfinished claims never masquerade as completed judgments.
- Eight browser tests passed across desktop and mobile viewports; production TypeScript/Vite build succeeded.
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
