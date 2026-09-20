# HypeCheck, pitch, four tracks, and the film

## The one line

**Paste a health video. Get back what the research actually says, and whether a
human wrote the script.**

## The thirty second version

Health advice on short video is confident, fast, and often wrong. HypeCheck takes
a Reel or a Short, transcribes it, pulls the medical claims out, and checks each
one against published literature down to the exact sentence in the exact paper.

Then it does something nobody else does. It tells you whether the creator wrote
that script or a language model did.

We measured that at scale. **162 videos: 6.1% of health shorts are read off a
machine-written script, and they hold 0.0018% of the views.** Follow one back to
its channel and nearly everything there is synthetic too.

---

# The four tracks

## 1. GPTZero

**Lead with this one. It is the strongest claim we have.**

Their brief asks for investigations into how far AI slop has penetrated the
online world, and for mapping the spread. We did that, with numbers, not vibes.

**What we used, three separate APIs:**

- Detection with the **subclasses**, so we separate `pure_ai` from
  `ai_paraphrased`, which is a machine script deliberately pushed through a
  humaniser to evade them
- **AI Patterns**, streamed, naming the specific tell in the specific sentence:
  Phantom experts, Everything in threes, Sales-pitch tone
- Per-sentence probabilities, which is what lets us shade the transcript

**The investigation.** 162 videos across 40 health topics, transcribed locally.
6.1% machine-written. Then we traced flagged videos back to their channels and
scanned everything those channels published: **44 of 48, and three of the four
channels are 100% synthetic.**

**The line that will land.** We tested their `highlight_sentence_for_ai` flag and
refused to ship it. On a genuinely mixed document it returned true for **9 of 9
sentences, including one scoring 0.1795**. Building on that would have shaded a
real creator's own words as machine-written, in public, next to their name. So we
threshold the probability ourselves at 0.5, and we can show the measurement that
chose that number: a creator's ad-lib scored 0.18 and 0.29, the script around it
0.74 to 1.00.

**Tell them what we disproved.** We built a disfluency remover on the theory that
speech fillers mask machine authorship. Measured it across eight samples. It
never changed a single verdict. We shipped it switched off and wrote down why.
Their founders abandoned fact-checking for being hard to verify, so a negative
result we can defend is worth more to them than a feature we can't.

## 2. Elastic

**This is a real retrieval story, not a search box bolted on.**

- Passages are chunked from real papers carrying **absolute character offsets**,
  so every quote can be shown inside the paragraph it came from. A validator
  refuses to construct a passage whose offsets do not reproduce the text exactly.
- **Hybrid retrieval**: BM25 plus ELSER semantic, fused with **reciprocal rank
  fusion**.
- Retrieval is **filtered to the passages discovered for that one claim**, which
  is what prevents cross-claim and cross-case leakage from a shared index.
- **Two-stage degradation.** If semantic indexing fails, only the failed subset
  retries as keyword, and the mode is carried all the way to the interface as
  "Keyword only, degraded retrieval". It never silently pretends to be hybrid.

**What to show:** open the Research trail drawer. It prints the exact query and
the retrieval mode per claim. That is the thing most teams cannot show.

## 3. Sentry

Their brief asks for the bug your traces caught, not a screenshot of the SDK.

- Distributed tracing across API, Celery worker and browser, with a span per
  pipeline stage and the case duration on the transaction
- **Scrubbing is tested, not assumed.** A test asserts the prompt text and the
  audio never appear in serialized spans, and the log allowlist is six fields
  wide so a future caller cannot leak a transcript by accident
- A **cron monitor**, so a dead worker surfaces as a missed check-in rather than
  silence
- A gated failure-injection endpoint, so recovery can be demonstrated on command

**Be honest:** confirm a real finding has landed in a connected workspace before
claiming one. The docs currently say that gate is unexercised.

## 4. Rox

Their brief: agents that handle unstructured, incomplete or noisy data.

**What to say:** our input is a person talking, and we never control the quality.
We get noisy speech through a lossy transcriber and still produce either a
sourced verdict or an explicit refusal.

**The evidence is funny and real.** On live runs the transcriber turned
"adenosine" into "penicillin", "sleep debt" into "sleep death", and "five to six
hours" into "05:55". The pipeline completed correctly anyway, and the authorship
detector still scored the script at 1.0000.

This costs no code changes. Frame the submission properly and it qualifies.

---

# The video: how to shoot and cut it

The product is about **receipts**. Every cinematic choice should serve that. If
it looks like a hype reel, it undermines the thesis.

## The governing rule

**Show the artifact, not a description of the artifact.** Real paper typography,
real highlighted sentence, real transcript. The moment anything looks generated,
the credibility premise collapses, which is exactly the failure mode we are
supposed to be detecting.

## The opening, first 8 seconds

Do not open on the logo. Open on the **problem in the wild**: a real health short
playing full frame, someone saying something confident and wrong. Let it breathe
for three seconds. Then a hard cut to the claim pinned on screen.

The viewer should feel the claim before they see any product.

## The signature shot, build this first

> The claim sits on screen. Cut to the paper, full frame, in its real
> typography, journal header visible. The camera **pushes in slowly** on the
> relevant paragraph. As it settles, the evidence sentence **highlights, sweeping
> left to right at reading speed**, synced to the narrator reading that exact
> sentence aloud. Then the study-design badge and `n = 31,521` land beside it.

That single shot is the whole product in four seconds. Everything else is
decoration around it.

## The second signature shot, and this one is ours alone

The transcript, scored sentence by sentence, **shading in as it scores**. Red
creeping across the scripted lines, green staying on the creator's own words.
Hold on the boundary where the creator went off-script. That is a visual nobody
else at the event has.

## Cutting rules

- **Cut on narration, not on the beat.** This is an evidence explainer, not a
  trailer. Let sentences finish.
- **Motion means attention.** Push-ins always move *toward* the highlighted text.
  Nothing teleports, nothing bounces.
- **Numbers get their own moment.** Sample size, the verdict, the 6.1%. One large
  element, held long enough to actually read.
- **One saturated colour.** Let the highlight and the verdict be the only vivid
  things on screen. Everything else stays calm.
- **No stock footage, no generated b-roll, no avatar.** For this product
  specifically those are a liability, not a flourish.
- **Captions TikTok-style, word level**, big and high contrast, kept clear of the
  platform's own interface zone.

## Structure for a 60 second cut

| Time | Beat |
|---|---|
| 0:00 | The bad claim, playing raw |
| 0:08 | Paste the link. Let the latency show |
| 0:15 | The signature shot: paper, push-in, highlight, narration |
| 0:28 | The verdict, large and unambiguous |
| 0:34 | The transcript shading red and green. "And a machine wrote this" |
| 0:45 | The investigation number: 6.1%, and 0.0018% of views |
| 0:55 | The refusal. One claim where it says uncertain |

Ending on the refusal is deliberate. It is the most trustworthy thing the product
does.

## What to cut if it runs long

Cut the product tour. Cut the architecture. Never cut the signature shot or the
refusal.

---

# Talking to judges

## The five minutes, same script four times

**0:00 to 0:30.** "Find me any health video. Your phone, any one." They pick. It
runs. Say almost nothing while it works, the screen is doing the talking.

**0:30 to 1:30.** The evidence card lands. Point at the highlighted sentence
inside the real paragraph. Read the badge aloud.

**1:30 to 2:30.** The authorship panel. Scripted lines red, their own words
green. This is where you watch the judge lean in.

**2:30 to 3:30.** The refusal, and why it matters. Then the investigation number.

**3:30 to 5:00.** Their questions.

## The four questions you will get

**"How do I know it isn't making the papers up?"**
It can't. The model picks from a numbered catalog of real sentences we sliced out
of the papers ourselves, and we copy the text out rather than accepting what it
wrote. A fabricated citation isn't rejected, it's unrepresentable. Three separate
gates re-check it anyway.

**"What if the research is thin?"**
It says `uncertain` and shows you why. We keep that strictly separate from
`incomplete`, which means a service failed. A timeout never becomes a medical
opinion.

**"Isn't this just asking ChatGPT?"**
For one person asking one question, a chat model is fine. What it can't do is
watch a video nobody asked about, point at the exact sentence, refuse when the
evidence is thin, and do it 162 times over a weekend.

**"Does the AI detection actually work?"**
Real creator speech scores 0.0001. A machine script scores 1.0000, and it stays
at 1.0000 after a human reads it aloud with fillers piled on while the
transcriber mangles three words. We have the paired measurements and we'll show
you the ones that disproved our own first idea.

## Tone

Lead with the measurement, not the ambition. Concede the obvious criticism before
they raise it. The teams that win are the ones who clearly know where their own
work is weak.

## Do not claim

Tiger Data (we use plain PostgreSQL), ElevenLabs (narration is OpenAI TTS),
Baseten (unused). Claiming a track you did not build for is the fastest way to
lose the four you did.

## Known weak spots, so nothing ambushes you

- The 90 second target has one measured run behind it, not a distribution
- The investigation is YouTube Shorts only. TikTok and Instagram are walled off
  without a login or paid scraping, and we say so rather than pretending
- Retrieval quality is unmeasured: `evaluation/queries.json` has empty
  `expected_paper_ids`
- Have a pre-rendered video on standby. Rendering live in front of a judge is
  dead air you do not need
