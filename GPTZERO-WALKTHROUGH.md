# GPTZero in MedBot: the full walkthrough

Read this top to bottom once. Then you can pitch it without notes.

---

## The 20 second version

MedBot checks health claims in short videos against published research.
GPTZero answers a second question: **was this script written by a machine?**

We use three GPTZero APIs (Application Programming Interfaces).
We tested them on our own voices before trusting them.
Then we pointed them at 473 health videos, 3,456 papers and 5,206 citations.

The headline: **0% of 2022 papers read as machine-written. 47% of 2026 papers do.**

---

## 1. Normal use: someone pastes a video

This is what happens every single time. No special mode.

| Step | What runs | Why |
|---|---|---|
| 1 | We download the audio and whisper.cpp transcribes it | GPTZero scores sentences. YouTube auto-captions have no punctuation, so it saw 0 or 1 sentence. Whisper gives real sentences. |
| 2 | The transcript goes to `POST /v2/predict/text` | One call. About 1 s. |
| 3 | We strip speech fillers and send it a second time | "um", "uh", "like", "basically". People add these when reading a script aloud. |
| 4 | The Authorship card shows both readings | Separate card. It never touches the medical verdict. |

Step 2 runs **in parallel** with the literature search. It adds no waiting time.
Our first live case took 15.3 s end to end.

### What GPTZero sends back

- A class: `HUMAN_ONLY`, `MIXED` or `AI_ONLY`
- Three probabilities that sum to 1: human, mixed, AI
- A score for **every sentence** (`generated_prob`, from 0 to 1)
- A subclass: `pure_ai`, `ai_paraphrased` (run through a humaniser), `concatenated` (human and machine parts stitched), `polished`

### What we do with it

- A sentence at 0.5 or higher is painted orange. Lower is green.
- One orange sentence alone is normal. Every sentence gets its own score. One line is weak evidence, so judge by the count.
- GPTZero splits on full stops. "(e.g., ref. 12)." leaves "12 )." behind as a sentence with a score. That is noise. We fold fragments under 25 characters back into the sentence they came from.
- We show the counts. "7 of 9 sentences read as scripted."
- We say "reads as", never "is". It is a signal, not a verdict.

### The guards

- Under 200 characters: we skip it and say so. Too short to judge.
- No key or GPTZero down: the card says "unavailable". Everything else still works.
- The detector can never crash a case. It always returns an answer, even if the answer is "could not check".

### What does NOT run on a video

The citation check. A video has no reference list. That check belongs to papers (section 3).

---

## 2. We tested it on ourselves first

Before building anything, Ezechiel dictated samples out loud. Real voice, real fillers.

| Sample | GPTZero AI score |
|---|---|
| Improvised speech, three topics | 0.0000 to 0.0027 |
| AI script, typed | 1.0000 |
| AI script, read aloud | 1.0000 |
| AI script, read aloud with heavy fillers | 1.0000 (lowest seen: 0.9993) |
| AI script with human ad-libs inside | ad-lib sentences 0.18 and 0.29, script sentences 0.74 to 1.00 |

What this told us:

1. **Reading a script aloud does not hide it.** Fillers do not fool the detector.
2. **Ad-libs show up as green islands.** That is why we score per sentence.
3. **0.5 is the right line.** Human lines sat under 0.30. Script lines sat over 0.74.
4. **Filler stripping never changed a verdict.** Eight samples, zero flips. We keep it as a second reading because it costs nothing and shows our work.

Two traps we fell into, and say openly:

- We first tried to validate with "human" text the model wrote itself. It scored 1.0. **You cannot test a detector with text a model wrote.**
- GPTZero's own `highlight_sentence_for_ai` flag marked 9 of 9 sentences, including one at 0.18. We ignore it and threshold the raw score ourselves.

---

## 3. The cascade: when the expensive checks fire

GPTZero gives us 30,000 detection calls per hour. It gives only 10 citation scans per minute.
So we spend the slow check where it matters.

```
every paper  ->  detection (fast, cheap)
                     |
           reads as machine-written?
                     |
                    yes  ->  bibliography scan (slow)
                                 |- does each citation exist?
                                 |- is each claim cited at all?
                                 |- does the source agree with the claim?
```

One bibliography call answers all three questions.
Machine-written papers go first. Prestige journals go first inside that group.

We also call `POST /v3/ai/patterns/stream` on flagged videos.
It names the tells: "Everything in threes", "Sales-pitch tone", "Phantom experts", "Not just X but Y".

---

## 4. The data

### Papers (3,456 open-access papers from Europe PMC)

| Year | Scanned | Read as machine-written | Share |
|---|---|---|---|
| 2022 | 35 | 0 | 0% |
| 2023 | 37 | 0 | 0% |
| 2024 | 1,666 | 265 | 16% |
| 2025 | 334 | 119 | 36% |
| 2026 | 1,384 | 653 | 47% |

- Overall: 1,037 of 3,456. That is 30%.
- 12 papers read as `ai_paraphrased`. GPTZero thinks a humaniser was used to hide it.
- Our control: a 2026 PLoS Medicine paper scores 0 of 45 sentences. Same kind of journal, same year, clean. So the tool is not just flagging academic prose.
- Showpieces: a Nature Medicine paper at 57 of 57 sentences. A PNAS paper at 75 of 82.

### Videos (473 health Shorts)

- 26 read as machine-scripted. That is 5.5%.
- They drew 134,823 of 17,063,638 views. That is 0.79%. **The feed is not flooded yet.**
- But channels that do it, do it every time. We followed the flagged channels: 44 of 48 more videos flagged.

### Citations (5,206 citations in 140 papers)

GPTZero called 73 of them fake. We did not take its word.

| What we found | Count |
|---|---|
| Real. Found on Crossref with the full title. | 35 |
| Real title, invented authors | 4 |
| Books, reports, websites. No database covers these. | 23 |
| Journal articles we cannot find anywhere | 11 |

**The best single example.** A 2026 PLoS One paper on Alzheimer's prediction.
GPTZero flagged seven references in a row (numbers 29 to 36).
We checked each by hand:

- Four exist nowhere. Not on Crossref. Zero exact-title hits on Europe PMC.
- Three are real papers cited under the wrong names. One "Cureus 2024" citation is really a PLoS One 2023 paper by other people.

Link: https://europepmc.org/article/PMC/PMC12810829

---

## 5. "Prove the Crossref check works"

Fair question. We measured it. `scripts/prove_crossref.py` does this:

- Takes 30 real references whose DOI (Digital Object Identifier) is printed in the paper.
- Removes the DOI from the text. Asks our check to find it blind.
- Builds 20 fakes: 12 chimeras (half of one real title glued to half of another) and 8 invented from nothing.

| Rule | Real ones found | Fakes wrongly cleared |
|---|---|---|
| Our first rule (any 25 shared characters) | 27 of 30 | **11 of 20** |
| Our strict rule (whole title, plus an author or the year) | 28 of 30 | **0 of 20** |

The strict rule returned the **exact same DOI** the paper printed 27 times out of 28.

What the test caught:

1. Our first rule was broken. "Alzheimer's disease classification" is 34 characters, so any paper on the topic "matched". It had cleared 5 of the 7 bad references above.
2. Crossref rate-limits. We were reading a refusal as "not found". That made 28 of 30 real references look fake. Now a refusal is retried, then reported as "could not check".

Honest limit: the strict rule still misses about 1 real reference in 15. So "not found" is a lead, not a conviction.

---

## 6. What we changed about GPTZero

We do not touch the model. We wrap it.

| Our layer | What it adds |
|---|---|
| Whisper transcripts | Gives the detector real sentences from speech |
| Filler stripping | A second reading on the cleaned text |
| Our own 0.5 threshold on sentence scores | Replaces their highlight flag, which over-flags |
| The cascade | Spends the 10 per minute citation budget on machine-written papers first |
| The verification layer | Every "fake" label is looked up on Crossref and ClinicalTrials.gov before we repeat it |
| Stored sentence maps | Every scan keeps its per-sentence scores, so any result can be shown and audited |

---

## 7. Shortcomings. Say these before a judge does.

- **Register, not authorship.** Formal, tidy writing can score high. Our most-viewed flagged video is a UCLA Health explainer. It may be a false alarm.
- **Paraphrasing AI text by hand still scored 0.90.** The detector reads style.
- **Open-access papers only.** We declined to scrape paywalled papers.
- **Small early samples.** 35 papers for 2022. Read the trend, not the decimals.
- **We retracted one claim.** "Prestige journals are cleaner" was confounded by year. We removed it.
- **Books and websites cannot be verified.** 23 of the 73 flags sit outside any database.

---

## 8. The 45 second pitch

> "MedBot checks health claims against research. GPTZero answers the second question: who wrote this?
>
> We tested it on our own voices first. Improvised speech scored zero. An AI script read aloud, with every um and like, scored one. Ad-libs show up as green sentences inside an orange script.
>
> Then we scaled it. 3,456 papers. Zero percent machine-written in 2022. 47 percent in 2026.
>
> GPTZero flagged 73 citations as fake. We did not trust that, so we built a checker and tested the checker: it finds 28 of 30 real references and clears 0 of 20 fakes. With it we found a 2026 paper with seven bad references in a row. Four do not exist. Three are real papers under invented names.
>
> It is a signal, not a verdict. So we show every sentence and every link, and let people look."

---

## 9. Questions they will ask

**"How do you know it is not just flagging formal writing?"**
The control. A 2026 PLoS Medicine paper scores 0 of 45. And 72 papers from 2022 and 2023 score 0%.

**"Does it change the medical verdict?"**
Never. Separate card, separate call. A machine-written script can still be true.

**"What if GPTZero is down?"**
The card says unavailable. The fact-check still completes.

**"Why strip fillers if it changes nothing?"**
We measured that it changes nothing. That is the finding. We keep it visible as a second reading.

**"What would you do with more time?"**
TikTok and Instagram at scale. Paywalled papers through a licensed route. A second reference database beside Crossref.

---

## Where everything lives

| Thing | Place |
|---|---|
| Detector | `backend/app/detection.py` |
| Filler stripping | `backend/app/speech.py` |
| Authorship card | `frontend/src/Authorship.tsx` |
| Investigation section | `frontend/src/Investigation.tsx` |
| Its numbers | `scripts/build_ui_data.py` writes `frontend/src/investigation.json` |
| Paper scanner | `scripts/paper_scan.py` |
| Citation scanner | `scripts/citation_pass.py` |
| Citation verifier and its proof | `scripts/verify.py`, `scripts/prove_crossref.py` |
| All raw data | `datasets/` |
| Hand-checked bad citations | `datasets/review/candidates.json` |
