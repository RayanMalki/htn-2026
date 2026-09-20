# Compact MedBot UI verification — 2026-09-20

## Mobile usability follow-up

Input focus now outlines the field container rather than overlapping the submit
button. Added a non-playing portrait video preview, a sources-and-ranking dialog,
a plain-language medical disclaimer, bordered nonzero result counts and adjacent
share/save actions. Removed the redundant numbered summary row. Repeated general
limits are deduplicated inside the sources dialog rather than displayed above the
video. New model judgments request everyday language; saved findings are unchanged.

Checks: 54 existing desktop/mobile browser tests plus 2 new phone-width checks
passed; 45 backend contract/pipeline tests and Ruff passed. Production Docker
builds passed. Saved live case `2de4aa16-0bef-4925-b2a9-c85ce77c9008` played its
60.1-second 720×1280 video in the viewer; Range 206, caption/source/replay 200,
no page errors. No new billed model request was made. The LAN URL returned HTTP
200 from the Mac. A physical phone and Wi-Fi client isolation were not tested.

## Follow-up refinement

- Combined the intake and introduction into one scanner card; kept Meet MedBot.
- Replaced inline video and download buttons with a compact Watch explanation
  card and accessible large dialog. Captions, expiry handling, Escape and focus
  return are preserved. Download API endpoints remain intact.
- Smaller sans-serif claim cards, darker copy, GPTZero gradient and an explicit
  hallucination-check Not run state. No hallucination API result is fabricated.
- Evidence displays saved retrieval ranks with a relevance/quality distinction.
  Uncertain findings expose their saved explanation and limitations in the summary.
- Fixed Elastic cache refresh when known_retracted changes, with regression tests
  for both changes to and from retracted. Existing candidate/retraction filters and
  source-diversity limits remain intact.
- Final checks: 54 desktop/mobile browser fixture tests; 66 research, detector and
  contract tests; Ruff; TypeScript/Vite and all affected Docker images passed.
- Saved live case `bb314fb6-2c29-4233-ae7f-e0af62dc150d`: scored real-transcript
  GPTZero result, all three retrieval modes hybrid, 58.067-second 720×1280 video
  played in the dialog. Range 206; captions/sources/replay 200; no page errors.
  No fresh billed analysis or hallucination API call was made.
- GPTZero public material documents citation-hallucination checking, but a supported
  API request/response contract was not located. Sponsor API docs/access are needed
  before implementing that feature. Authorship scores do not substitute for it.
- All changes remain uncommitted.

Base: `2201bba`, branch `codex/medbot-ui-integration`. Changes are intentionally
uncommitted. No secrets, generated media or dependencies are intended for Git.

Updated headline and subtle local texture; removed Observatory and placeholder
homepage topics; shortened claim cards with expandable original text and full
assessments; scanner-style render progress; redesigned GPTZero probabilities,
confidence, sentence signals and limitations; compact evidence summary before
sharing. Backend schemas, API routes and `result.video` are unchanged.

## Fixture checks

- Desktop/mobile Playwright suite: 52 passed, covering submission, upload fallback,
  SSE stale-event protection, retries, evidence, authorship unavailable/scored
  states, video controls/download links, and native/clipboard/manual sharing.
- After the final long-claim preview refinement: 8 targeted desktop/mobile checks
  passed, including full qualifier recovery, carousel navigation and 320px reduced
  motion. Browser fixtures do not measure provider accuracy or actual uploads.
- GPTZero backend tests: 19 passed; Ruff passed. Test provider keys were blanked
  in the process environment; the ignored local credentials were not changed.
- TypeScript and Vite production build passed inside the web Docker image.

## Actual localhost checks

Used saved live case `e3d3c178-375b-416d-acd4-644aaa51a8b5`. No fresh billed
analysis or detector call was required for this UI change. Its saved detection
was `scored`, `prepared_transcript=false`, confidence `high`; all three claims
reported hybrid retrieval. These are saved provider outputs, not fixture data.

The updated UI played the existing 720×1280, 65.3-second video. Playback time
advanced without media errors. Video Range request returned 206; captions,
sources and offline replay returned 200. No browser page errors were observed.
Screenshots are ignored files under `artifacts/revised-*.png`.

The earlier blanket 45–60-second statement is not the current renderer contract:
AGENTS.md and VIDEO.md specify 45–120 seconds. This UI change does not alter video
generation, estimated caption timing or scientific validity of model verdicts.
The live services were not benchmarked afresh. Sentry DSNs remain unconfigured.

## Compatibility

Fetched `origin/main` at `1ce02d1`. `git merge-tree --write-tree HEAD origin/main`
completed without conflicts. The uncommitted frontend edits do not overlap files
changed upstream relative to the merge base. This checks the current state only;
fetch and repeat before a later merge. No commit, push, or branch merge was made.
