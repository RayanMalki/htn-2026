# HypeCheck, how it works and what was hard

Send it a health video. It transcribes the speech, pulls out the medical claims,
checks each one against published literature down to the exact sentence in the
exact paper, tells you whether the script was written by a person or by a
machine, and renders a rebuttal video.

A real run, measured end to end on 2026-09-20:

| Stage | Seconds |
|---|---|
| download | 4.758 |
| audio extraction | 0.243 |
| transcription | 5.329 |
| authorship detection | 0.775 |
| literature research | 3.387 |
| judgment | 1.510 |
| **total** | **15.349** |

The target was 90 seconds. Input was a real YouTube Short about berberine.
Output: 15 candidate papers from Europe PMC, six retrieved passages, a verdict of
`uncertain` because the supporting evidence was in mice using different
compounds, and an authorship reading of `AI_ONLY` at 1.0000.

## Getting a video in

Three accepted link forms, normalised on arrival in `schemas.py`:

- `instagram.com/reel/...` and `/reels/...`
- `youtube.com/shorts/...` and `m.youtube.com`
- `youtu.be/...`, rewritten into the Shorts form, because that is what the
  YouTube app's share sheet actually hands out

Anything else is refused. Tracking parameters are stripped rather than trusted.

A link can also arrive as `?url=...`, which fills the box and submits itself
(`App.tsx:145`). That is the path for an iPhone share-sheet shortcut, a QR code
on the table, or a bookmarklet. A judge shares straight from the YouTube app and
the analysis is already running when the page opens.

---

## The pipeline

`backend/app/pipeline.py` runs one coroutine, `run_case`, as a Celery task.
Every mutation writes a numbered, immutable snapshot to PostgreSQL before Redis
is told anything, so the record survives a crash and the browser can replay it.

```
link ─► download ─► audio ─► transcribe ─► ┬─ research each claim ─┐
                                            └─ authorship detect ──┴─► judge ─► render
```

| Stage | Status | Bound |
|---|---|---|
| download | `downloading` | 15 s |
| audio | `transcribing` | ffprobe 5 s, ffmpeg 10 s |
| transcribe | `transcribing` | 25 s |
| research and detect | `researching` | 35 s per claim |
| judge | `judging` | 20 s per claim |
| render | `rendering` | 150 s |

Stages one to four sit inside a 120 second analysis deadline. Rendering is
deliberately outside it with its own 150 seconds, so a slow video can never eat
the fact-check's budget.

**Three providers behind one interface.** `models()` routes on `MODEL_PROVIDER`.
OpenAI is the default and uses `whisper-1` for speech plus `gpt-4.1-mini` for
extraction. Backboard and Gemini are drop-in alternatives. All three inherit the
same judgment method and citation validator, and only override transport and
audio handling, so the safety machinery cannot diverge between providers.

**Authorship detection runs inside the same `asyncio.gather` as the literature
research**, so it costs no wall clock at all.

---

## The authorship detector

`backend/app/detection.py` and `backend/app/speech.py`. One question: **was this
script written by a person or by a machine?** It never touches the medical
verdict, and a detector failure never fails a case.

### What GPTZero actually returns

One call to `POST /v2/predict/text` gives back far more than a score:

- `document_classification`: `HUMAN_ONLY`, `AI_ONLY` or `MIXED`
- `class_probabilities`: three numbers over human, ai and mixed, summing to 1
- `subclass`, empty for human text, otherwise saying *how* it was made:
  - under `ai`: `pure_ai` (straight from a model) or `ai_paraphrased` (pushed
    through a humaniser to evade detection)
  - under `mixed`: `concatenated` (human and machine blocks stitched) or
    `polished` (a person wrote it, a model smoothed it)
- `sentences[]`, each with its own `generated_prob`
- `paragraphs[]`, each with `completely_generated_prob`
- `average_generated_prob`, literally the fraction of sentences flagged

A second call to `POST /v3/ai/patterns/stream` returns server-sent events naming
the writing habits behind the verdict, each with the offending sentence, an
explanation, and how much more common that habit is in machine text:

> "However, emerging research suggests that their high omega-6 content may
> contribute to chronic inflammation."
> → **Phantom experts**, 1.9× more frequent in machine text
> → *"The claim is attributed to 'emerging research' without naming any specific
> study or authority."*

The transcript renders sentence by sentence, shaded where `generated_prob >= 0.5`,
labelled "read from a script" against "the creator's own words".

---

## The four hardest problems

### 1. Making a model structurally unable to fabricate a citation

This is the best piece of engineering in the repo and prompting alone did not
achieve it. `docs/VERIFICATION.md` records the real failure: on a live case, all
three judgments died because the model's quotes "were not verbatim". It was
paraphrasing the evidence it was told to quote.

The fix has three parts that compose:

**Slice the source, do not let the model write it.** `quotation_catalog()` splits
every retrieved passage on sentence boundaries, preserving punctuation and
whitespace exactly, and numbers the slices `q1`, `q2`, and so on.

**Build a schema whose enum is that catalog, per request.**

```python
selection_schema = create_model("SelectedVerdict", __base__=SelectedVerdict,
    quote_ids=(list[Literal[tuple(catalog)]], Field(max_length=6)))
```

The model can only emit IDs that exist. A hallucinated citation is not rejected
after the fact, it is unrepresentable.

**The application writes the citation, not the model.**

```python
citations=[catalog[key] for key in dict.fromkeys(result.quote_ids)]
```

Then `validate_verdict()` re-checks substring containment anyway, and the video
renderer re-checks it a third time before anything is rendered. Three independent
gates on the same invariant.

### 2. A failure must never become a medical opinion

`uncertain` is a finding. `incomplete` is an outage. Collapsing the two would let
a network timeout masquerade as a considered medical judgment, and that
distinction is enforced in five separate places with near-identical wording:

- research failure writes "Medical research could not complete. No verdict was assigned."
- the outer handler writes "No unsupported verdict was assigned."
- a conclusive label with zero citations raises
- Elasticsearch returning 503 in keyword mode re-raises rather than returning an empty list
- a supplemental provider outage is appended to the verdict's own limitations

The regression test is one line, and it is the product's spine:

```python
assert "verdict" not in case["result"]["claims"]["c1"]
```

### 3. The authorship premise was wrong, and measurement said so

The founding idea: spoken delivery is full of "um" and "like", those
disfluencies read as human to a detector, so a machine-written script performed
aloud would slip through. Strip the fillers and the script is unmasked.

The whole filler remover was built. It handles vocalised noise, discourse
markers, filler phrases and self-repairs, and it keeps "like" and "kind of"
where they carry meaning, so "it looks like a meta-analysis" survives while
"it is, like, huge" does not.

Then it was measured:

| Sample | Verbatim | Fillers stripped |
|---|---|---|
| Improvised speech, filler-heavy | human 0.0000 | human 0.0001 |
| Improvised speech, polished register | human 0.0001 | human 0.0001 |
| Real creator's caption | human 0.0001 | not run |
| Model script, typed | ai 1.0000 | ai 1.0000 |
| Model script, fillers inserted by hand | ai 1.0000 | ai 1.0000 |
| **Model script, read aloud into dictation** | **ai 1.0000** | **ai 1.0000** |

The last row is decisive. A real person read a model-written script aloud,
adding "like" and "basically" unprompted, while the transcriber mangled three
words beyond recognition (`sleep debt` became `sleep death`). The floor across 13
sentences was **0.9993**.

Stripping fillers never changed a single classification across eight samples.

The literature agrees. Deezer ran the same pipeline for song lyrics
([arXiv 2506.18488](https://arxiv.org/abs/2506.18488)): *"We also experimented
with various types of post-processing, such as text normalization ... but none of
these improved detection performance."*
[Stumbling Blocks, ACL 2024](https://aclanthology.org/2024.acl-long.160/)
explains why: character noise destroys perplexity-based detectors (GLTR retains
2% of its accuracy) while fine-tuned classifiers score **108% to 112%**, meaning
noise pushes them *further* toward the right answer. GPTZero is the second kind.

**What shipped:** the whole subsystem, behind `GPTZERO_FILLER_READING`, default
off. The local filler counts still display at no API cost. A feature built,
disproved, and kept switched off is more honest than deleting the evidence.

### 4. Trusting the vendor's highlight flag would have libelled real creators

GPTZero returns `highlight_sentence_for_ai`, and their engineer said in the
sponsor talk not to build your own heuristic on top of the probability.

Tested on a genuinely mixed document (scripted intro, real ad-lib, back to
script) it returned **true for 9 of 9 sentences, including one scoring 0.1795**.
Shipping that would have shaded a creator's own words as machine-written, in
public, next to their name.

Their documentation explains it: the flag requires *both* the sentence and **its
paragraph** to clear a threshold. In a mostly machine-written document the
paragraph gate opens and everything trips.

So the flag is ignored and `generated_prob` is thresholded directly at 0.5, a
number taken from measurement rather than taste:

| Ground truth | Score |
|---|---|
| script | 0.7422 |
| **ad-lib** | **0.1795** |
| **ad-lib** | **0.2863** |
| script | 0.9938 to 0.9998 |

A gap of about 0.45 with nothing in between. The README states plainly that this
threshold is a user-interface heuristic and not proof of authorship.

**One honest caveat.** The detector separates on *how text was produced*, not who
typed it. When a human paraphrased a model-written paragraph, keeping its shape,
their sentences scored **0.90**. When the same person spoke off the cuff, 0.18.
Reworded model output still reads as machine-written, which is arguably correct.

**A methodological trap worth recording:** every "human-sounding" control sample
written to test this scored `ai=1.0000`. Correctly. They were written by a
language model, so they *were* machine text. **You cannot validate an AI detector
with text you generated.** The human controls had to come from a real person
dictating and from a real creator's caption.

---

## Other things that were harder than they look

**Two silent ffmpeg traps**, both of which produce a playable file, which is the
worst possible failure mode. From the code comments:

> "`black@0.0` quietly becomes opaque black and the caption track blacks out
> every frame between captions. That happened, and the test now checks a pixel
> for it."

> "Switching between RGB caption PNGs and the RGBA gap frame reinitializes the
> filter graph, discarding the scene transitions and cutting the video stream
> short."

The second is why a test measures the *video stream* duration separately from
the container duration. The container was lying.

**Checkpoints that can be wrong.** Naive resume is a bug factory, so the renderer
verifies content hashes of every produced file rather than its existence, and
invalidates downstream cascadingly: *"Once a stage is invalid, downstream records
must never be reused on a later retry."* The artifact fingerprint covers the
renderer version, the voice, the tone string, a hash of the alignment model file
itself, and the source clip bytes, so changing any of them produces a new
directory rather than silently reusing stale work.

**A script budget that sacrifices the right thing.** If narration exceeds 60
seconds, source cards are dropped first and limitations are never trimmed:
*"Evidence reading time is optional; medical wording and limitations are not."*
If it still does not fit, it fails loudly rather than clipping a qualification
mid-sentence.

**Killing a detached browser tree.** Playwright starts Chromium in its own
process group, so cancellation walks the descendant list first (captured before
any signal, so it is not racing itself), kills deepest-first, then signals the
group, then reaps. Tested by spawning a grandchild with `start_new_session=True`.

**Server-side request forgery, in two layers.** The hostname is resolved and
rejected if not globally routable. Then `socket.getaddrinfo` is monkeypatched
*inside the yt-dlp subprocess*, so a CDN redirect to a private address is caught
too, with the proxy environment disabled because *"a proxy could resolve private
destinations on our behalf."*

**A lock ladder, not three arbitrary numbers.** Worker hard limit 310 s, lease
330 s, abandoned-case recovery 360 s. The lease outlives the hard limit and
recovery outlives the lease, so a killed worker cannot leave a case both
unlocked and unprocessed.

**Server-sent events read the database, not the message bus.** Redis publication
is only a wake-up hint. The stream polls persisted events once a second so a
missed notification cannot lose a reconnecting client, and the row lock plus a
unique constraint on `(case_id, sequence)` makes every snapshot replayable in
order.

**The 100 second input limit is enforced four separate times**: in the yt-dlp
match filter, in the ffprobe assertion, as `-t 100` on the extraction, and as a
field constraint on every timestamp in the schema.

**Captions that never split a number from its unit.** Pages of two to four words,
with numbers glued to their units and range partners, because *"a page that says
'477' alone means nothing."*

---

## The investigation

`scripts/slop_scan.py` and `scripts/build_leaderboard.py` apply the same detector
in bulk: search YouTube Shorts across 40 health topics, pull audio only,
transcribe locally, score, rank.

**162 videos, in two cohorts kept deliberately separate.**

Topic sample, 114 videos, which is a population rate:

- **7 machine-written, 6.1%**
- Those 7 hold **50 views out of 2,835,198, or 0.0018%**
- The most-watched machine-written health video in the sample has **30 views**

Channel follow-up, 48 videos, which is **not** a rate because those videos were
chosen by pulling a thread:

- **44 of 48 machine-written, 92%**
- Three of the four channels are **100%** synthetic

Subclasses across everything: 47 `pure_ai`, 2 `concatenated`, 2 `polished`.
Pattern hits: Sales-pitch tone 66, Everything in threes 40, Not just X but Y 7,
Overblown importance 5, Phantom experts 4, Empty commentary 2.

**In one sentence:** machine-written health advice is being mass-produced on
dedicated channels, and almost nobody is watching it.

### Scanning was harder than scoring

GPTZero was never the bottleneck. Acquisition was.

- **About 85% of YouTube Shorts refuse the audio download.** Confirmed as
  per-video protection rather than throttling by retrying the same videos across
  five player clients and every format selector. Failures are cached and skipped.
- **`curl_cffi` 0.16.3 was too new.** yt-dlp supports up to 0.15.x, so
  impersonation was silently unavailable and every target read "(unavailable)".
- **An 8 GB machine could not take Whisper at default thread count.** Killed three
  times. Capped to two threads, and discovery now runs once into a queue file.
- **YouTube's own captions have no punctuation.** A 3,000 character transcript
  reached the detector as `0/1` sentences. That is a confident wrong answer
  rather than an error, which is why transcription is local Whisper instead.
- **TikTok and Instagram are walled off** without a login or paid infrastructure,
  so the investigation is labelled YouTube Shorts rather than pretending
  otherwise.

---

## What is not verified

- The 90 second goal is a target. One live run finished in 15.3 seconds. That is
  one run, not a distribution.
- Retrieval quality is unmeasured by construction: `evaluation/queries.json` has
  empty `expected_paper_ids`.
- `known_retracted` is never set true by any code path. Retraction handling is
  the Europe PMC query clause plus a publication-type check, which the README
  correctly describes as "not a complete retraction registry".
- Browser tests verify the interface contract, not model accuracy.
- The investigation covers YouTube Shorts only, and the sample is what was
  reachable rather than a random draw.
- Authorship measures how words were produced, never whether a claim is true. A
  creator speaking off the cuff can still be completely wrong.
