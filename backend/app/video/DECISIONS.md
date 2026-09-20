# Renderer decisions — version 3

This file supersedes the pre-merge experimental provider and compositor notes.

- **One renderer:** `app.video` is the package. The conflicting `app/video.py` has
  been removed, along with the superseded `artifact.py` and `pipeline_adapter.py`
  generation paths. Automatic generation and manual requests use the same Celery path.
- **One claim:** earliest contradicted claim, otherwise earliest assessed claim.
  This is an editorial selection, not a new medical verdict. The saved label,
  explanation and limitations are preserved and other findings remain in the app.
- **Evidence:** labeled excerpts from validated stored passages. We do not imitate
  a screenshot or claim that abstract access means a full paper was read. Citation
  counts do not establish the number or stance of studies.
- **Voice:** OpenAI using existing model/voice settings. Explicit provider errors
  replace the prototype's silent fallback. No ElevenLabs/Gemini/macOS auto-fallback.
- **Timing:** local pinned whisper.cpp/base.en operates on generated audio. Timing
  must match the script and stay within the audio. Estimates are disclosed when
  alignment fails; the source clip uses coarse transcript segment captions.
- **Layout:** preinstalled Playwright/Chromium and local DejaVu fonts render cards.
  Excerpts have safe-area/overflow checks. No runtime npm installs or web fonts.
- **Composition:** FFmpeg H.264/AAC, 720×1280, 30 fps, faststart MP4. Original speech
  and generated narration never overlap. Captions follow post-processing.
- **Reliability:** a bounded process tree owned by the worker, atomic checkpoints,
  cache keys covering semantic inputs and voice settings, integrity-checked stage
  artifacts, and explicit errors. Video failures preserve completed findings.
- **Scope:** source shots and citations are real stored text; no generated medical
  imagery, numerical truth scores, or social publishing. Split-screen remains an
  optional local-media/procedural effect, off by default.

The 90-second end-to-end goal is a target, not a promise. The analysis deadline is
120 seconds and rendering has a separate 150-second deadline. See the verification
record for the distinction between fixture tests and live acceptance.
