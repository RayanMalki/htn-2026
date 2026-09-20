# GPTZero: what we use, what we changed, what it can't do

Everything here was measured in this project. Where a number appears, we ran it.

---

## 1. What we actually use

Five things, not one. Most teams will use the first and stop.

| What | Endpoint | What it gives us |
|---|---|---|
| Document class | `POST /v2/predict/text` | `HUMAN_ONLY`, `AI_ONLY` or `MIXED`, with probabilities over all three |
| **Subclass** | same response, `subclass` field | *How* it was made, not just whether |
| **Per-sentence** | same response, `sentences[]` | A probability per sentence, which is what lets us shade a transcript |
| **AI Patterns** | `POST /v3/ai/patterns/stream` | The named writing tell, in the specific sentence, streamed |
| **Bibliography scan** | `POST /v2/bibliography-scan/text` | Whether the citations in a paper resolve to real sources |

### The subclass field is the underused one

It is empty for human text. Otherwise:

- Under `ai`: **`pure_ai`** (straight out of a model) or **`ai_paraphrased`** (a
  model script deliberately pushed through a humaniser to evade detection)
- Under `mixed`: **`concatenated`** (human and machine blocks stitched together)
  or **`polished`** (a person wrote it, a model smoothed it over)

Across our 162 scanned videos: **47 `pure_ai`, 2 `concatenated`, 2 `polished`.**

`ai_paraphrased` is the one worth having. Reading a script is careless.
Laundering it through a humaniser is deliberate, and it is a different accusation.

### AI Patterns is the most explainable output

Instead of a probability, you get a quoted sentence and a reason:

> "However, emerging research suggests that their high omega-6 content may
> contribute to chronic inflammation."
> → **Phantom experts**, 1.9× more frequent in machine text
> → *"The claim is attributed to 'emerging research' without naming any specific
> study or authority."*

Hits across our scan: Sales-pitch tone 66, Everything in threes 40, Not just X
but Y 7, Overblown importance 5, Phantom experts 4, Empty commentary 2.

It stays quiet on human text, which is what makes it useful. Our human samples
returned `{"warning":"No patterns were found for the given text"}`.

---

## 2. What we changed

Six departures from their defaults. Each one has a measurement behind it.

### We ignore their highlight flag

`highlight_sentence_for_ai` is meant to save you writing a heuristic. We tested
it on a genuinely mixed document: a scripted intro, a real ad-lib, then back to
script. It returned **true for 9 of 9 sentences, including one scoring 0.1795.**

Their own documentation explains why. The flag requires the sentence **and its
paragraph** to clear a threshold, so in mostly-machine text the paragraph gate
opens and everything trips.

Shipping that would have shaded a real creator's own words as machine-written,
in public, next to their name. So we threshold `generated_prob` ourselves at 0.5.

### The 0.5 threshold is measured, not chosen

From a recording where the speaker read a script, went off-script for a minute,
then returned:

| Ground truth | Score |
|---|---|
| script | 0.7422 |
| **ad-lib** | **0.1795** |
| **ad-lib** | **0.2863** |
| script | 0.9938 to 0.9998 |

A gap of roughly 0.45 with nothing in between.

### We transcribe locally instead of using platform captions

YouTube's auto-captions have no punctuation:

> `physician welcome to another video seed oils are absolutely everywhere they are`

GPTZero splits on sentences, so a 3,000 character transcript arrived as
**`sentences flagged: 0/1`**. One sentence. No sentence-level data at all, and a
machine-written script would have come back the same shape. That is a silent
false negative, the worst kind of failure.

We use `whisper.cpp` locally, which writes punctuated prose, runs at about 13×
realtime and costs nothing.

### We built a filler-stripper, disproved it, and shipped it switched off

The founding theory: speech is full of "um" and "like", those read as human, so a
machine script read aloud would slip through. Strip the fillers to unmask it.

We built it. Then measured it:

| Sample | Verbatim | Fillers stripped |
|---|---|---|
| Improvised speech, filler-heavy | human 0.0000 | human 0.0001 |
| Improvised speech, polished | human 0.0001 | human 0.0001 |
| Real creator's caption | human 0.0001 | not run |
| Model script, typed | ai 1.0000 | ai 1.0000 |
| Model script, fillers added by hand | ai 1.0000 | ai 1.0000 |
| **Model script, read aloud into dictation** | **ai 1.0000** | **ai 1.0000** |

The last row is the decisive one. A person read a model-written script aloud,
adding "like" and "basically" unprompted, while the transcriber mangled three
words (`sleep debt` became `sleep death`). Floor across 13 sentences: **0.9993**.

Stripping never changed a single classification in eight samples.

The literature agrees. Deezer ran the same pipeline for lyrics
([arXiv 2506.18488](https://arxiv.org/abs/2506.18488)) and found normalization
did not help. [Stumbling Blocks (ACL 2024)](https://aclanthology.org/2024.acl-long.160/)
explains the mechanism: character noise destroys perplexity-based detectors
(GLTR keeps 2% of its accuracy) while fine-tuned classifiers score **108 to
112%**, meaning noise pushes them further toward the right answer.

It lives behind `GPTZERO_FILLER_READING`, default off.

### We added a date gate they don't have

Bibliography scanning only runs on papers published after **2022**. A malformed
citation in a 2007 paper is human sloppiness. In a 2024 paper it is a different
question. Without this gate the check produces noise that looks like a finding.

### We do not use their source finder for medical claims

Their `sources` output is general web search. On a health claim it returned
**`seedoilscout.com`** and **`thewholehealthpractice.com`**, and seven of nine
stances came back `neutral`.

Ours is Europe PMC with study-design weighting, citation ranking, retraction
filtering and exact character offsets. For medicine that difference is the
product.

### And it never touches the verdict

Authorship is quarantined. `Detector.scan()` always returns, never raises. A
missing key, a short transcript, an upstream error and a malformed response are
each reported inside the result. An authorship check cannot take down a medical
fact-check.

---

## 3. The chain-of-custody check

The newest idea, and it came out of asking: we cite a paper as evidence, but has
anyone checked that *paper's* citations?

**How it works.** Take a paper we cited, pull its reference list out of the
Europe PMC full text, and send it to Bibliography Scan. Statuses come back as
`exist`, `exist_with_issues`, `fake`, `unsure` or `unknown`.

**What we found on a real 2025 paper we cited:** 83 references, 40 scanned,
**21 `exist` and 19 `exist_with_issues`.**

**And then we checked what those 19 actually were**, which matters. Every one
carried `hallucination_label: None` and the explanation *"The citation exists but
has minor issues: some components do not match the source."* The reference text
we extracted had mangled spacing, which almost certainly broke component
matching.

**So the honest result is: zero hallucinated citations found.** That is the
reassuring answer for peer-reviewed work, and it is what we will say. Reporting
"19 problems found" would have been wrong.

---

## 4. How the 162-video scan actually worked

No browser and no Playwright. Playwright is in this repo, but only for rendering
video cards. The scan is `yt-dlp` plus local Whisper.

```
yt-dlp "ytsearch36:seed oils inflammation #shorts" --skip-download --print "..."
```

A search behaves like a playlist, so metadata for hundreds of videos is nearly
free. That gave **601 candidates** across 40 topics (now 58).

Then, per video: download audio, transcribe with Whisper, send to GPTZero twice.

### Why downloading is unavoidable

We are not scoring the title. We are scoring **the spoken script**, and those
words only exist inside the audio. There are two ways to get them, and platform
captions are ruled out by the punctuation problem above. So: audio, then Whisper.

### The refusal, and how it was solved

YouTube hands over metadata freely and then refuses the **media stream** with a
403 on most Shorts. Confirmed as per-video and permanent by retrying across five
player clients and every format selector.

Original result: **601 attempted, 162 scanned, 439 refused. 27% success.**

**The fix: a signed-in session.** With `--cookies-from-browser safari`, the same
videos download. Tested on five previously-refused videos: **5 of 5 succeeded.**

One catch worth recording. On the signed-in path YouTube offers **no audio-only
stream**, so `-f bestaudio` fails with "requested format is not available", which
looks like a different bug entirely. The fix is a fallback chain
`bestaudio/91/18/worst` to the smallest combined format, then strip the audio
with ffmpeg.

Requests are paced with `--sleep-requests`, because this runs against a real
account.

### Efficiency note

Channel sweeps beat topic search: 48 scanned from 90 discovered (**53%**) versus
114 from 511 (**22%**). Enumerating a channel directly is roughly twice as
efficient, and it is how the content farms were found.

---

## 5. Shortcomings

### Theirs

- **The highlight flag is paragraph-contaminated.** 9 of 9, including 0.1795.
- **It measures register, not authorship.** A human paraphrasing model text,
  keeping its shape, scored **0.90**. The same person speaking off the cuff
  scored 0.18. Reworded model output still reads as machine-written, which is
  arguably correct but must be stated.
- **Sentence-level runs on a separate, weaker classifier**, per their own
  engineer.
- **The source finder is unsuitable for medicine.** SEO blogs.
- **Bibliography scan cannot see spoken citations.** "A 2019 Harvard study" is
  invisible to it, because it parses formal reference lists.
- **Speech is out of distribution.** Their docs say training is "majority English
  prose, written by adults", and the HANSEN benchmark measured them at 0.57 to
  0.62 precision on human interview transcripts in 2023.

### Ours

- **n = 162** is modest, and a 73% refusal rate means it was never a random draw.
  The cookie fix should change both, and the scan is rerunning now.
- **YouTube Shorts only.** TikTok blocks impersonation and its profile listing is
  broken upstream. Instagram needs a login.
- **The chain-of-custody check has been run on one paper.**
- **It cannot run inline.** Bibliography scan is 10 requests per minute and takes
  seconds per call, so it cannot sit in a 90 second pipeline. It belongs in a
  background pass.
- **We have never seen a genuine `fake`** in our domain, only `exist` and
  `exist_with_issues`. We do not know what a true positive looks like here yet.
- **Whisper transcripts differ slightly from the audio**, so a scored sentence is
  a close paraphrase of what was said, not a legal transcript.

---

## 6. The one-sentence version

We use five GPTZero capabilities, we overrode their highlighting because it
would have libelled real creators, we built a feature on a premise their own
domain disproved and shipped it switched off, and we pointed their citation
checker at the papers we cite rather than at the video.
