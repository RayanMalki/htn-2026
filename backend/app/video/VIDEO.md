# Staged fact-check videos (renderer version 4)

The app automatically renders a complete live analysis when `VIDEO_ENABLED=true`.
It selects the earliest contradicted claim, otherwise the earliest assessed claim.
The finished video targets 45–120 seconds and shows only that claim. The app retains
all other assessments. Mock, no-claim, incomplete, and invalid-citation analyses
cannot produce medical videos.

## Stages and evidence

`script → voice → cards → compose → post → captions`

A short, complete timestamped claim excerpt plays with its original audio when the
source is available and the excerpt is at most eight seconds. Otherwise a labeled
claim card is used. AI narration begins after original audio ends. Cards reproduce
stored source excerpts, not screenshots of journal pages. Quotations are validated
against stored passages; full quotations, source URLs, provider/access labels, the
saved verdict, and all its limitations remain in the downloadable manifest.

The script does not infer individual study stances from the overall verdict. Counts
refer to unique cited papers and health summaries separately. Optional excerpt shots
are removed before any essential wording is dropped. If essential narration exceeds
120 seconds, rendering fails with `script_budget_exceeded`; it never clips speech or
silently removes limitations. Shorter scripts leave time to read the closing card.

## Configuration

- `OPENAI_API_KEY`, `TTS_MODEL=gpt-4o-mini-tts`, `TTS_VOICE=coral`: narration.
- `VIDEO_ENABLED=true`: automatic generation for live analyses.
- Rendering has no overall deadline. Provider calls and alignment retain bounded waits.
- `VIDEO_ENCODER_PRESET=veryfast`, `VIDEO_ENCODER_THREADS=2`: benchmarkable encoder settings.
- `WHISPER_MODEL=/opt/whisper/ggml-base.en.bin`: local alignment model.
- `HYPECHECK_PLAYWRIGHT_DIR`: optional path to preinstalled Playwright.
- `PLAYWRIGHT_BROWSERS_PATH`: browser installation location.

The image installs pinned Playwright/Chromium, local fonts, whisper.cpp v1.7.6 and
an immutable base.en model revision at build time. Nothing is installed or fetched
for layout at render time. Host development needs these same tools plus FFmpeg and
FFprobe. Readiness/preflight report renderer dependencies when live video is enabled.

OpenAI failures are explicit; there is no production silent or alternate-provider
fallback. Local Whisper aligns the audio actually generated. If alignment cannot be
validated, captions use estimates and the app/manifest disclose that. Original clip
captions use transcript segment timing. Artificial silent audio is allowed only when
explicitly invoked by test fixtures.

## App and API

- `POST /api/cases/{id}/render?brainrot=false&sfx=true` queues a completed live analysis.
- `POST /api/cases/{id}/retry` resumes saved analysis/render work.
- `GET /api/cases/{id}/video` streams the MP4 with Range support; `?download=true` saves it.
- `/video/captions` returns WebVTT; `/video/sources` returns the source/script manifest.

Generation requests use the same Celery worker and `result.video` contract. Its statuses are
`pending`, `rendering`, `ready`, and `failed`; `stage` provides progress. Identical
requests reuse pending work or the existing artifact. Video failures preserve medical
findings. Case status remains `incomplete` until rendering succeeds, with the separate
video error explaining which part failed.

Artifacts live in `MEDIA_ROOT/<case_id>/video/<content-hash>/`. Atomic stage checkpoints
and validated audio caches survive retries. The content hash includes input evidence,
source bytes, rendering options, model/voice/instructions, alignment model path and
renderer version. Bump the renderer version when script, layout or encoding behavior
changes so existing checkpoints cannot mask a code change. Completed version-2 artifacts remain readable. The former `VIDEO_RENDERER` switch and duplicate adapters are removed; changing it no longer selects a second implementation. Legacy `result.render`
records must be regenerated; their filesystem paths are never served.

Media expires after 24 hours. Active rendering is excluded from cleanup. Download the
MP4, captions and manifest for offline use; stored medical findings remain available.

## CLI

```sh
PYTHONPATH=backend python -m app.video.render case.json data/manual-render \
  --source-clip original.mp4 --no-sfx
```

The supplied JSON must satisfy the same live/complete/citation checks as the app.
Outputs are under a content-hash subdirectory, with `plan.json`, `checkpoint.json`,
`response.mp4`, `captions.vtt` and `manifest.json`. The root `result.json` describes the
latest completed artifact. The bundled blue-light JSON is a synthetic contract fixture,
not verified medical evidence or a live acceptance case.

Sound effects default on. `--brainrot` enables split-screen; `--gameplay FILE` supplies
a licensed local clip. Without it, a procedural pattern is used. ASS captions are applied after layout in the combined encode so they stay at the split-screen seam. Social publishing is not implemented.


## Performance pipeline (version 4)

Narration requests have concurrency two; local word alignment remains serial.
Browser card layout overlaps narration. The voice cache is retained across visual
changes. Narration durations and word timings are both divided by the 1.25 playback
rate; original source audio is not accelerated. Complete explanations and every
limitation are retained rather than truncating narration at a word count.

Composition retains integrity-keyed scene clips for recovery, then performs one
final encode containing transitions, optional split-screen, ASS captions, disclosure,
and sound mixing. The post checkpoint is a compatibility bookkeeping stage; captions
only publishes the final MP4 and downloadable VTT. No caption PNGs or separate
caption video encode are used in production. Legacy helpers remain for comparisons.

Stage fingerprints hash their source dependencies. The API checks the full renderer
identity before returning a cached ready result. Visual changes invalidate layout and
encoding, not narration. A changed scene gets a new clip key; interrupted unchanged
scene rendering can resume. The manifest records request, alignment, scene encoding,
final encoding and aggregate stage durations. Nested durations must not be summed
with their parent stages. Cached runs explicitly list reused stages.

`scripts/benchmark_video.py` produces isolated fresh audio/render caches with one or
more concurrent runs from a saved live analysis. These are rendering benchmarks, not
fresh research or intake benchmarks. Keep all generated output outside Git.
