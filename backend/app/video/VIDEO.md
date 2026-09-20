# The rebuttal video: how to run it

The renderer turns a finished case into a vertical MP4: the original clip, the claim frozen on screen, the paper with the exact sentence highlighted, the finding, and a close, with a voice reading a script in which every factual line carries an evidence id. This file is the how-to. `DECISIONS.md` next to it is the why.

## How the stages fit

Every stage reads and writes one object, `RenderPlan` in `plan.py`. Stages never call each other, so each can be built, tested and swapped alone.

| Stage | Reads | Writes |
|---|---|---|
| **Script** | the case: claim, evidence, finding | `plan.scenes` (each with `narration` and a `card`) and `plan.evidence` |
| **Voice** | every scene's `narration` | `plan.voice`: `audio_path`, `duration`, `engine`, `words` with `start` and `end`, and `timings_from` |
| **Cards** | each scene's `card` | each scene's `card_png`, and for the paper scene a `focus_box` so the camera can push toward the highlight |
| **Compose** | scenes, card images, voice, `source_clip` | `plan.output_path`, the MP4 |
| **Post** | the MP4, `plan.sfx`, `plan.brainrot`, `plan.gameplay_path` | the final MP4 with sound effects and, when asked, the split screen |

The fields that matter most:

- `Card.highlight` is the exact sentence to sweep-highlight on the paper scene, and `Card.highlight_section` names where it came from (RESULTS, CONCLUSIONS). That is the signature shot, so it has to be the sentence the evidence table actually cites.
- `Evidence.access` is one of `full_text`, `free_needs_browser`, `abstract_only`. The card shows it. Never let the video imply the machine read a whole paper it did not.
- `Finding.label` is `supported`, `contradicted`, `mixed`, `unclear` or `insufficient`, with a plain `sentence` and counts. **There is no score anywhere in the plan and there must not be one on screen.**
- `RenderPlan.duration` is the voice length once the voice exists. Scenes are timed to the narration, not the other way round.

## Rendering a case

Once the orchestrator lands, one command:

```
python -m app.video.render <case_id>
```

It writes the plan next to the output as `<case_id>.plan.json` so any stage can be rerun alone by loading and saving the plan, which is also how a failed stage is retried without redoing the voice.

Default output is 720 by 1280 at 30 frames per second, H.264 with the moov atom at the front, AAC audio. That is accepted by both TikTok and Instagram Reels, see the platform section of `DECISIONS.md`. The file must be reachable at a public URL to publish through either API, so the tunnel that serves the page serves the video too.

## Which key switches which engine on

| Variable | Effect |
|---|---|
| `ELEVENLABS_API_KEY` | Voice from ElevenLabs, with word timings straight from the engine. First choice, and a sponsor track |
| `OPENAI_API_KEY` | Voice from OpenAI speech when ElevenLabs is not set. Word timings then come from a local whisper pass on the rendered audio |
| neither | The macOS `say` voice, then whisper for timings. Robotic but never rate limited |
| no voice engine at all | A silent track of the planned length, so a render never fails for lack of a voice |

`plan.voice.engine` records which one actually ran, and `timings_from` records where the caption timings came from (`engine`, `whisper`, `estimated`, `none`). If a demo video sounds wrong, look there first.

Voice files are cached by the hash of the narration, so re-rendering a video does not spend credits again. The ElevenLabs free tier is roughly a dozen renders a month without the cache.

## Toggles

Sound effects and the split screen are plan fields, settable from the environment when rendering:

```
SFX=0 python -m app.video.render <case_id>          # no whoosh, pop or thud
BRAINROT=1 python -m app.video.render <case_id>     # split screen on
```

- `sfx` (default on) mixes a whoosh on every scene change, a pop when the study badges land, and a thud when the finding card lands. All three are synthesized by ffmpeg, nothing downloaded.
- `brainrot` (default off) puts the rebuttal in the top 760 pixels over a blurred copy of itself and a muted looping gameplay clip in the bottom 520, captions at the seam.

## Dropping in a gameplay clip

Put a vertical clip at the path in `plan.gameplay_path`, or the default `backend/app/video/assets/brainrot.mp4`. The compositor loops it, mutes it, and crops it to fill the bottom pane. Without a file it uses a procedural Mandelbrot zoom, which proves the layout and compresses badly (about 45 MB for 45 seconds), so a real clip is smaller as well as better.

Do not use a capture of Subway Surfers itself. The game is copyrighted and a stock upload cannot license it. Pick a lookalike endless runner or an original render from Pixabay or Pexels. The searches are linked in `DECISIONS.md`.

## Before judging: pre-render

Even a fast render is 30 to 90 seconds of dead air on stage. Before Sunday morning:

1. Render **two or three example videos** from the demo set and keep the files on the laptop and on a phone. The blue-light video is the best one, because the honest verdict is mixed and the video says so, which is the "it is not a contrarian machine" moment.
2. Keep one **true-claim video** rendered, so a judge sees the system agree with a creator.
3. Run the whole thing once with the wifi off, from the cached plan. If it cannot render dark, the pre-rendered files are the demo, and say so plainly rather than waiting on a spinner.

## What to check when something looks wrong

| Symptom | Where to look |
|---|---|
| Captions drift from the voice | `plan.voice.timings_from`. If it says `estimated`, whisper did not run |
| The highlighted sentence is not the cited one | `Card.highlight` must equal the `Evidence.quote` for that scene's `evidence_id` |
| A paper card claims full text on an abstract | `Evidence.access` is wrong upstream, fix the resolver output, not the card |
| The video is huge | The gameplay pane is the Mandelbrot stand-in, drop in a real clip |
| Render fails with no voice | It should not, the silent fallback exists. If it does, the voice stage raised instead of returning `engine: silent` |
