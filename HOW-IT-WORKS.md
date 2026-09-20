# HypeCheck, how it works and what was hard

Paste a link to an Instagram Reel or a YouTube Short. HypeCheck transcribes the
speech, pulls out the medical claims, checks each one against the published
literature down to the exact sentence in the exact paper, tells you whether the
script was written by a person or by a machine, and renders a rebuttal video.

A real run, measured end to end on 2026-09-20:

| Stage | Seconds |
|---|---|
| download | 4.758 |
| audio extraction | 0.243 |
| transcription | 5.329 |
| **authorship detection** | **0.775** |
| literature research | 3.387 |
| judgment | 1.510 |
| **total** | **15.349** |

Target was 90 seconds. Input was a real YouTube Short about berberine
supplements. Output: 15 candidate papers from Europe PMC, six retrieved
passages, a verdict of `uncertain` because the supporting evidence was in mice
using different compounds, and an authorship reading of `AI_ONLY` at 1.0000.

---

## The pipeline

`backend/app/pipeline.py` runs one function, `run_case`, as a Celery task. Every
stage appends an event row to PostgreSQL before anything is published to Redis,
so the record survives a crash and the browser can replay it.

```
link ─► download ─► audio ─► transcribe ─► ┬─► research each claim ─┐
                                            └─► authorship detect ──┴─► judge ─► render
```

1. **Download** (`media.py`). `yt-dlp` with a 15 second timeout. Private network
   redirects are rejected. If the platform blocks it, the case moves to
   `awaiting_upload` rather than failing, and the user can hand it a file.
2. **Audio** FFprobe validates duration, FFmpeg extracts the track.
3. **Transcribe** (`models.py` → `openai_models.py` / `backboard.py` / Gemini).
   `models()` routes on `MODEL_PROVIDER`. The default is OpenAI, which uses
   `whisper-1` for speech and `gpt-4.1-mini` for claim extraction.
4. **Research and detect, concurrently.** Up to three claims each run a tiered
   Europe PMC search plus MedlinePlus, chunk the results into passages carrying
   absolute character offsets, index them into Elasticsearch, and retrieve with
   BM25 and semantic search fused by reciprocal rank fusion. Authorship
   detection runs in the same `asyncio.gather`, so it costs no wall clock.
5. **Judge** The model may only cite retrieved passages, and every quotation is
   checked to be a literal substring before the verdict is allowed to render.
6. **Render** (`backend/app/video/`) A separate 150 second deadline. Failure here
   preserves the findings.

Two deadlines, deliberately separate: 120 seconds for analysis, 150 for
rendering. Partial results are always kept.

---

## The authorship detector, in detail

This is `backend/app/detection.py` and `backend/app/speech.py`. It answers one
question: **was this script written by a person or by a machine?** It never
touches the medical verdict, and a detector failure never fails a case.

### What GPTZero actually returns

One call to `POST https://api.gptzero.me/v2/predict/text` gives back more than a
score:

- `document_classification`: `HUMAN_ONLY`, `AI_ONLY` or `MIXED`
- `class_probabilities`: three numbers over human, ai and mixed, summing to 1
- `subclass`, which is empty for human text and otherwise says *how* it was made:
  - under `ai`: `pure_ai` (straight from a model) or `ai_paraphrased` (pushed
    through a humaniser to evade detection)
  - under `mixed`: `concatenated` (human and machine blocks stitched together)
    or `polished` (a person wrote it, a model smoothed it)
- `sentences[]`, each with its own `generated_prob`
- `paragraphs[]`, each with `completely_generated_prob`
- `average_generated_prob`, which is literally the fraction of sentences flagged

A second call to `POST https://api.gptzero.me/v3/ai/patterns/stream` returns
server-sent events naming the specific writing habits behind the verdict, each
with the offending sentence, a written explanation, and a multiplier for how much
more common that habit is in machine text. On a real scanned video:

> "However, emerging research suggests that their high omega-6 content may
> contribute to chronic inflammation."
> → **Phantom experts**, 1.9× more frequent in machine text
> → *"The claim is attributed to 'emerging research' without naming any specific
> study or authority."*

### How the interface uses it

The transcript renders sentence by sentence, shaded where
`generated_prob >= 0.5`, labelled "read from a script" against "the creator's own
words". The threshold is not a guess. It comes from a measurement described below.

---

## The four things we got wrong first

Everything here is something we built or assumed, then measured, then corrected.

### 1. The founding premise was wrong

The original idea: spoken delivery is full of "um" and "like", those
disfluencies read as unmistakably human to a detector, so a machine-written
script performed aloud would slip through. Strip the fillers and the script would
be unmasked.

So `speech.py` was built: it removes vocalised noise, discourse markers, filler
phrases, and immediate self-repairs, while keeping "like" and "kind of" where
they carry meaning (guarded by the preceding word and by a comma test, so "it
looks like a meta-analysis" survives and "it is, like, huge" does not).

Then it was measured, and the premise collapsed:

| Sample | Verbatim | Fillers stripped |
|---|---|---|
| Improvised speech, filler-heavy | human 0.0000 | human 0.0001 |
| Improvised speech, polished register | human 0.0001 | human 0.0001 |
| Real creator's caption | human 0.0001 | not run |
| Model script, typed | ai 1.0000 | ai 1.0000 |
| Model script, fillers inserted by hand | ai 1.0000 | ai 1.0000 |
| **Model script, read aloud into dictation** | **ai 1.0000** | **ai 1.0000** |

The read-aloud test is the decisive one. A real person read a model-written
script into a dictation tool, adding "like", "basically" and "you know"
unprompted, and the transcriber mangled three words beyond recognition
(`sleep debt` became `sleep death`). The floor across 13 sentences was **0.9993**.

Stripping fillers never changed a single classification in eight samples.

The literature agrees. Deezer ran the same pipeline for song lyrics
([arXiv 2506.18488](https://arxiv.org/abs/2506.18488)) and reported: *"We also
experimented with various types of post-processing, such as text normalization
... but none of these improved detection performance."* And
[Stumbling Blocks, ACL 2024](https://aclanthology.org/2024.acl-long.160/)
explains the mechanism: character-level noise destroys perplexity-based
detectors (GLTR retains 2% of its accuracy under a typo attack) but fine-tuned
transformer classifiers score **108% to 112%**, meaning noise nudges them
*further* toward the correct answer. GPTZero behaves like the second family.

**What shipped:** the whole subsystem, behind `GPTZERO_FILLER_READING`, default
off. The local filler counts still display at no API cost. A feature we built,
disproved, and kept switched off is more honest than deleting the evidence.

### 2. YouTube's own captions would have silently poisoned everything

The batch scanner nearly used YouTube auto-captions, which are free and need no
download. They come back like this:

> `physician welcome to another video seed oils are absolutely everywhere they are also known as vegetable oils`

No punctuation. GPTZero splits on sentences, so a 3,000 character transcript
arrived as **`sentences flagged: 0/1`**. One sentence. No sentence-level data at
all, and a machine-written script would have returned the same shape and likely
scored human.

That is a false negative that produces confident, wrong output rather than an
error. The fix was `whisper.cpp` locally, which writes properly punctuated prose,
runs at roughly 13× realtime (3.1 seconds for a 40 second clip) and costs nothing.

### 3. The vendor's own highlight flag is unusable

GPTZero returns `highlight_sentence_for_ai`, and their engineer said in the
sponsor talk that you should use it rather than build your own heuristic.

We tested it on a genuinely mixed document: a scripted intro, a real ad-lib, then
back to script. It returned **true for 9 of 9 sentences, including one scoring
0.1795**. Building the highlight on that flag would have shaded a creator's own
words as machine-written, in public, next to their name.

Their documentation explains it: the flag requires *both* the sentence and **its
paragraph** to exceed a threshold. In a document that is mostly machine-written,
the paragraph gate opens and everything gets flagged.

So `detection.py` ignores the flag and thresholds `generated_prob` directly. The
comment in the code says so, and the test asserts the parser ignores it.

The threshold of 0.5 comes from measurement. In a recording where the speaker
read a script, went off-script for a minute, then returned:

| Ground truth | Score |
|---|---|
| script | 0.7422 |
| **ad-lib** | **0.1795** |
| **ad-lib** | **0.2863** |
| script | 0.9938 to 0.9998 |

A gap of about 0.45, with nothing in between.

### 4. It measures register, not authorship, and that matters

One test cut the other way. When a human *paraphrased* a model-written paragraph,
keeping its shape and vocabulary, their sentences scored **0.90**, indistinguishable
from the machine sentences around them at 0.9997.

But when the same person spoke genuinely off the cuff, they scored 0.18.

So the detector separates on *how the text was produced*, not on who typed it.
Reworded model output still reads as machine-written, which is arguably correct:
"I reworded ChatGPT" is closer to AI-assisted than to human-written. The
interface says this in plain words rather than hiding it.

### A methodological trap worth recording

Every "human-sounding" control sample written to test this scored `ai=1.0000`.
Correctly. They were written by a language model, so they were machine text.

**You cannot validate an AI detector with text you generated.** The human controls
had to come from a real person dictating, and from a real creator's caption
pulled out of a downloaded video's metadata. That caption scored `human 0.0001`
while the synthetic "human" samples scored 1.0000, which is the detector working
exactly as it should and the experimenter being the unreliable component.

---

## Failure containment

`Detector.scan()` **always returns a `Detection`** and never raises. Four failure
modes, each reported inside the result instead of thrown:

| Condition | Result |
|---|---|
| No API key configured | `skipped`, with the variable name to set |
| Transcript under 200 characters | `skipped`, with the actual length |
| Upstream error or timeout | `unavailable`, "No authorship claim is made." |
| Malformed response | `unavailable` |

The pipeline call is wrapped again on top of that, because this is a side signal.
An authorship check must never be able to take down a medical fact-check.

---

## The investigation

`scripts/slop_scan.py` and `scripts/build_leaderboard.py` apply the same detector
in bulk: search YouTube Shorts on 40 health topics, pull audio only, transcribe
locally, score, and rank.

**162 videos scanned, in two cohorts kept deliberately separate.**

Topic sample, 114 videos, which gives a population rate:

- **7 machine-written, 6.1%**
- Those 7 hold **50 views out of 2,835,198, or 0.0018%**
- The most-watched machine-written health video in the sample has **30 views**

Channel follow-up, 48 videos, which is **not** a rate because those videos were
chosen by pulling a thread:

- **44 of 48 machine-written, 92%**
- Three of four channels are **100%** synthetic

Subclass distribution across everything: 47 `pure_ai`, 2 `concatenated`,
2 `polished`. Pattern hits: Sales-pitch tone 66, Everything in threes 40, Not
just X but Y 7, Overblown importance 5, Phantom experts 4, Empty commentary 2.

**The finding in one sentence:** machine-written health advice is being
mass-produced on dedicated channels, and almost nobody is watching it.

### Why scanning was harder than scoring

GPTZero was never the bottleneck. Acquisition was.

- **About 85% of YouTube Shorts refuse the audio download.** Verified as
  per-video protection rather than rate limiting by retrying the same videos
  across five player clients and every format selector. Same ones fail every
  time, so failures are cached and skipped on resume (439 cached).
- **`curl_cffi` 0.16.3 was too new.** yt-dlp only supports up to 0.15.x, so
  impersonation was silently unavailable and every target read "(unavailable)".
  Pinning to 0.15.0 fixed it.
- **An 8 GB machine could not take Whisper at default thread count.** The run was
  killed three times. Capped to two threads, and discovery (the memory-hungry
  step) now runs once into a queue file that later runs just drain.
- **TikTok and Instagram are walled off.** Instagram returns an empty media
  response without a login. TikTok blocks impersonation and its profile listing
  path is broken upstream. The investigation is labelled YouTube Shorts rather
  than pretending otherwise.

---

## What is not verified

- The 90 second goal is a target. One live run finished in 15.3 seconds. That is
  one run, not a distribution.
- The investigation covers YouTube Shorts only.
- Whisper transcripts can differ slightly from the spoken audio.
- Authorship measures how words were produced, never whether a claim is true. A
  creator speaking off the cuff can still be completely wrong.
- The sample is what was reachable, not a random draw, because of the 85%
  download refusal rate.
