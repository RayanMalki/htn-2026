# MedBot frontend: Sentry Replay

This folder already includes `@sentry/react` and `replayIntegration()` in
`src/main.tsx`. No separate Replay package, backend Replay integration, or Sentry
auth token is required. The SDK initializes only when `VITE_SENTRY_DSN` is set.

## Set up Sentry

1. Create or select a **React** project in your Sentry organization and copy its
   DSN from the project's **Client Keys (DSN)** settings.
2. Ensure Session Replay is available for your organization and has remaining
   quota. Use that React project when viewing **Replays**.
3. Configure the frontend environment below. Backend `SENTRY_DSN` is separate.

For local Vite development, copy `.env.example` to `.env.local` **in this folder**
and fill in the React DSN. From the repository root:

```sh
npm ci --prefix medbot-frontend-complete
npm --prefix medbot-frontend-complete run dev
```

Open http://127.0.0.1:5173. The API proxy expects a backend on port 8000.
Restart Vite after changing the environment. Do not run the other frontend's
development server on the same port.

```dotenv
VITE_SENTRY_DSN=https://YOUR_PUBLIC_KEY@YOUR_INGEST_HOST/YOUR_PROJECT_ID
VITE_SENTRY_ENVIRONMENT=development
VITE_SENTRY_REPLAY_SESSION_SAMPLE_RATE=0
VITE_SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE=1
```

These defaults upload replays for sampled errors and do not continuously upload
ordinary sessions. Set `VITE_SENTRY_REPLAY_SESSION_SAMPLE_RATE=1` temporarily to
record every session during setup, then restore `0` or choose a deliberate sample
between `0` and `1`. Trace and profile sampling are independent of Replay.

## Docker

The repository's default Compose configuration builds `frontend/`. To build and
serve **this folder**, put the `VITE_SENTRY_*` values in the repository-root `.env`
and run from the repository root:

```sh
docker compose -f compose.yaml -f medbot-frontend-complete/compose.override.yaml up -d --build web
```

The override keeps the existing backend/proxy settings and selects this folder's
Dockerfile. Vite settings are embedded at build time: rebuilding the web image is
required after changing them. A plain container restart does not update the bundle.
Native `.env.local` files are not the Docker configuration source.

## Verify recording

1. Load the app with your DSN configured and interact with the page for several
   seconds. For the default error-only configuration, run this in the browser's
   developer console after the SDK loads:

   ```js
   setTimeout(() => { throw new Error('MedBot Replay setup check'); }, 0);
   ```

2. Check browser network requests to your Sentry ingest host, then find the error
   and its associated replay in the React project. Match the environment filter.
3. Inspect the replay: text and input values should be masked and media blocked.
   This captures page structure and interactions, not the submitted video's content.

Replay masks all text/inputs, blocks media, and enables no unmask/unblock selectors.
Network request/response bodies are not opted into recording. Error/transaction
scrubbing is separate from Replay's privacy controls. Do not treat DOM masking as
a guarantee that URLs, console messages, or every metadata field are scrubbed.

If no replay appears, check that the DSN reached the built frontend, the sampling
rates are nonzero for the kind of session being tested, the environment filter is
correct, quota is available, and an ad blocker is not blocking ingestion. Custom
Content Security Policies must allow Sentry ingestion and Replay's worker (`worker-src
'self' blob:`). This repository's Caddy configuration does not currently set a CSP.

The DSN is public by design. Never place `SENTRY_AUTH_TOKEN` or provider API keys in
`VITE_*` variables. No production DSN is bundled in this repository.

Official references: [React Replay setup](https://docs.sentry.io/platforms/javascript/guides/react/session-replay/)
and [Replay privacy](https://docs.sentry.io/platforms/javascript/session-replay/privacy/).

## Local regression check

With Google Chrome installed, run from the repository root:

```sh
npm --prefix medbot-frontend-complete run test:replay
```

This starts an isolated Vite server on port 4175 with a fake DSN. It intercepts
ingestion, triggers an error, decodes the Replay recording, and checks that the
DOM text and entered URL are masked. It sends no events to a Sentry account and
does not call a medical provider or use saved cases. Regular UI tests exclude it
because it requires its own server configuration.

Verification on 2026-09-20, base `3995629` with the Replay/configuration changes in
this folder: the Chrome Replay regression passed, and TypeScript/Vite production
builds passed with and without a fake DSN. Dependency/build caches were used.
Remote Sentry ingestion and the full UI suite were not verified in this change.
