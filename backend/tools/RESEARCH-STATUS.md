# Where we are: reading papers, reasoning on them, seeing videos

Written Saturday Sept 19, 5:30 PM, during the code window. Everything below was measured on real papers and a real video today, not estimated.

## 1. Reading full papers

**Status: working, 5 of 8 landmark papers fully readable, up from 1 of 8 this morning.** (3 by script, 2 more by rendering in a headed browser, see the note under the table.)

The original backend (`app/literature.py`) reads full text only for papers that are open access inside PubMed Central. On the eight studies the blue-light creator cited on screen, that reached exactly one. Today's resolver (`resolver.py`) adds three layers and was tested against those same eight:

| Study | Before | After | Route |
|---|---|---|---|
| Brainard 2001 | abstract | **full text, 67,448 chars** | Europe PMC's own free-link list |
| Chinoy 2018 | full text | full text, 69,187 chars | Europe PMC XML (already worked) |
| Gooley 2010 | abstract | **full text, 83,841 chars** | DOI link in Europe PMC's list |
| Thapan 2001 | abstract | **full text, 26,824 chars, headed render** | Unpaywall found it, headless is blocked, headed passes |
| West 2011 | abstract | **full text, 76,032 chars, headed render** | Legacy domain dead, current one blocks headless, headed passes |
| Figueiro 2011 | abstract | abstract | No DOI, no free copy anywhere |
| Wood 2013 | abstract | abstract | Genuinely paywalled |
| Cajochen 2011 | abstract | abstract | Genuinely paywalled |

**The three access states the page must show**, because collapsing them is dishonest:

- `full_text`: the machine read the whole paper.
- `free_needs_browser`: a free copy exists but a headless fetch is blocked. **Render it headed** (`fulltext_render.mjs --headed`) and it reads fine, measured on both cases today. No stealth flags, no challenge solving: Cloudflare's automatic check blocks headless and passes a normal browser on its own. If a page ever escalates to an interactive CAPTCHA, stop and show the link for a person to click. This is not "paywalled."
- `abstract_only`: no free copy exists anywhere. The abstract still states the finding for reviews and meta-analyses (Cochrane abstracts run 5,000 to 6,500 characters and carry the pooled result and certainty rating).

**The resolver chain, in order:** Europe PMC full-text XML, then Europe PMC's own `fullTextUrlList` (the "free full text" links a human sees on the article page, which Unpaywall sometimes misses), then Unpaywall (PDF parsed with `pdftotext`, or HTML handed to the Playwright renderer), then the abstract with a badge.

**Bugs found and fixed today, all real:**
1. **Wrong-paper matches.** A loose title search returned a 2021 paper for a 2001 claim and a veterinary journal for a melatonin study. `verify_match()` now checks year and first author before trusting any candidate. Citing the wrong paper is worse than citing an abstract.
2. **Unpaywall DOI encoding.** Percent-encoding the slash in a DOI returns 422. Pass it raw.
3. **A dead host and a blocked host looked identical.** Connection refused (domain gone) and HTTP 403 (server refusing scripts) both came back as "no data," so a free-but-gated paper was mislabeled paywalled. `_get()` now returns the status and `_is_block_status()` tells them apart.
4. **Embargo labels.** Europe PMC marks some links `Free after 12 months`, not `Free`. For any paper older than a year that embargo has passed, so any label starting with `Free` counts, except `documentStyle: abs`, which is only the abstract page.
5. **Early return on the first blocked mirror.** A paper with several free mirrors was reported as gated when the first mirror was blocked but the second would have worked. Every mirror is tried for full text before falling back.
6. **Legacy journal domains.** `intl-jap.physiology.org` no longer resolves. `_candidate_urls()` rewrites known dead hosts to their current home.
7. **Socket exhaustion.** Firing requests back to back crashed the run with `Errno 49`. Requests are now spaced 0.35 s apart. This is the failure you get when three judges trigger at once.

**Deliberately not built, and why:** Sci-Hub (pirated copies), university library cookies (publisher licences ban scripted downloading and enforce it against the whole institution), and anything that defeats a bot challenge (an arms race, and the challenge is the publisher saying no to scripts on purpose). The `free_needs_browser` state exists so those papers are still one click away for a person.

## 2. Reasoning on papers

**Status: the engine works, and today it caught its own worst failure mode.**

The first run on the blue-light video pulled **one** sentence from **one** review that agreed with the creator and declared the claim supported. That is cherry-picking, the exact thing a fact-checker must never do. Weighing the creator's own eight cited studies, every one shows blue light suppresses melatonin or delays circadian timing, one of them dose-dependently. The honest verdict is **mixed and misleading**: he is right that pop culture overstates the effect and that brightness matters, and wrong to conclude blue light does nothing.

Three rules the engine must enforce, now written into the plan:
1. **Count both sides.** Retrieve supporting and contradicting studies, tally them, never verdict on one paper.
2. **Weight by design and species.** Human randomized trial beats human observational beats animal. A mouse study cannot outrank eight human studies on the same question.
3. **Separate the sub-claims.** "Blue light suppresses melatonin" (strongly true) is a different claim from "screens ruin your sleep" (weaker). Conflating them is how the creator misleads.

**Timing, measured:** each literature search 0.5 to 2.9 s, each full-text fetch about 0.2 s, PDF parsing under a second. Whole evidence chain about 2 s per claim.

## 3. AI-written detection on the papers themselves

**Status: built and tested, waiting on a GPTZero key to run live.**

`paper_authorship.py` scores a paper's full text with the same GPTZero request and parsing the transcript detector uses (`app/detection.py`), then stores the result in a SQLite table keyed by paper id. `cite_and_scan.py` hooks it to the resolver: every paper that comes back as full text gets scored automatically, so the database grows as a byproduct of normal citation, no separate crawl.

Scoped to full text only. Abstracts are too short and too terse for a style detector to read reliably.

Tested end to end with a synthetic GPTZero-shaped response: an AI-written paper parses to `AI_ONLY, pure_ai, 0.94`, a human one to `HUMAN_ONLY, 0.03`, the no-key and too-short paths return clean `skipped` statuses, and the report prints the share of cited papers reading as machine-written. Ran the real resolver into it on four papers: three reached full text and flowed through, one was abstract-only and skipped as designed. **No key was available anywhere on the machine**, so the three real scans are recorded as skipped. Set `GPTZERO_API_KEY` and rerun `cite_and_scan.py` to fill them in.

## 4. Seeing videos

**Status: download, transcribe, and creator lookup all work. Gemini and on-screen text are untested here.**

Tested on `@carterpcs`, 3.3M views, 40 seconds:

| Step | Result | Time |
|---|---|---|
| Metadata | 65 fields: views, likes, shares, saves, description, creator, date | 1 s |
| Download | 2.4 MB | 8 s on this connection |
| Transcribe | Local whisper, full transcript | **2 s** |
| Captions from TikTok | **None exist.** The words must come from the video | |
| Creator profile | Empty for this account, the scraper needs hardening | |

The 4-minute wait you saw was a one-time 141 MB model download, not the pipeline. On a pre-cached demo video the first finding lands in about 3 seconds. On a cold live video it is about 15, and 70% of that is the download. Pre-cache the demo set.

**Not yet verified here:** Gemini reading on-screen text from a silent video. That is the hour-4 gate in the plan and it still needs a key and three text-only test videos.

## 5. The judging rules, now as code

`weigh.py` turns the three rules from section 2 into one pure function. It counts both sides, weights each study by design (Cochrane above meta-analysis above randomized trial above observational above case report) and by species (human 1.0, animal 0.25, in vitro 0.1), drops retracted studies, abstains below two usable studies, calls "unclear" when the studies themselves could not decide, and calls "mixed" when both sides carry weight or when a side has only one paper, because one paper cannot win outright. The weights order and threshold, they are never shown. The page shows the label and the counts.

Fed the eight blue-light studies with the stances found in the papers, it returns **mixed**, which is the honest verdict, with six full-text and two abstract-only badges. Fed one agreeing review against five disagreeing trials, this morning's exact failure, it returns contradicted.

## 6. Where it can go wrong, tested

`test_failure_modes.py` is 31 tests across logic, inputs, robustness and speed. No pytest on this machine, so it carries its own runner. Run offline with `NETWORK=0` in about a second, or with the network for the timing checks.

Measured with the network on: one literature search 1.0 s, twelve spaced requests 11 s with zero socket errors, local transcription 4.9 s, a timeout to a dead address returns in under 2 s instead of hanging.

**The failure it found, and what it actually was:** a paper that was full text all day came back gated. First guess was a transient hiccup. Per-request timing showed the truth: Europe PMC's full-text endpoint answered **500 twice** and NCBI's BioC answered **429**. After a day of traffic from one address, plus a test suite that re-fetched every paper on every run, both services were throttling us, and the code fell through to a mirror that sits behind a permanent bot wall. That is exactly the venue scenario, 1,300 hackers behind one address.

Three fixes are in the resolver now. **A cache**, keyed by PMCID, DOI or PMID, so each paper is fetched once per machine: the second resolve of a known paper makes zero requests, which is also how the demo papers get pre-loaded before judging. **Throttle-aware backoff**, a longer pause on 429 and 500 before the retry, and BioC as a second official source. And **a rule about what to trust**: a result reached while a service was throttling is not cached unless it actually got full text, because "abstract only" under a 429 means "ask again later", not "no free copy exists". Two tests cover the cache: a second resolve makes zero requests, and a throttled non-full-text result is retried next time rather than locked in.

## 7. When the papers run thin

`websearch_fallback.py` fires only when fewer than two studies take a side, or every study is unclear. That guard is in the function, and a test proves a live key never reaches the network when two clear studies exist. It asks OpenAI's Responses API with the web search tool, restricted to eleven guideline and public-health domains (WHO, CDC, NIH, NHS, Health Canada, Cochrane and the like), for a stance and a short cited paragraph. Every result is badged `web_sources` with the text "From guidelines and public-health sources, not the primary literature", so the page never passes a web summary off as peer-reviewed evidence. Any numeric score the model emits is stripped. It runs on `gpt-5.6-terra`, about 0.006 dollars per call, and in mock mode without a key. Fourteen tests pass. `WIRING.md` names the exact line in `pipeline.py` where it slots in.

## 8. Video polish, built in the lab, to be ported

In `video-lab/ffmpeg/post.py`, two toggles on top of the finished render: `SFX=1` mixes a whoosh on every scene change, a pop when the study badges land and a thud when the finding card lands, all synthesized by ffmpeg from noise and sine waves, so nothing is downloaded or licensed. `BRAINROT=1` makes the split screen, rebuttal on top over a blurred copy of itself, a muted looping gameplay clip below, captions at the seam. The gameplay clip is whatever sits at `assets/brainrot.mp4`. Subway Surfers footage is copyrighted by its maker and is not fetched or bundled, pick a lookalike runner from a free-licence stock site. Without a file a Mandelbrot zoom stands in. The transitions in `render.py` are now fade, smoothup, circleopen and fadeblack, from the 59 this ffmpeg build supports.

That folder is a pre-event prototype, so `post.py` is not on the branch. Its logic is plain ffmpeg on a finished MP4 plus the cue times, and it ports as-is once the repo has its own renderer, which it does not yet.

## 9. Finding videos on our own, and scanning them

`crawl/` is the discovery crawler and transcript scan, the GPTZero track's first criterion and the feed for the leaderboard. Logged out, no login, no stealth, a headed muted browser with jittered scrolling and a cap of 30 per run.

**Which discovery routes work logged out, tested:**

| Route | Result |
|---|---|
| `tiktok.com/discover/<topic>` | **Works.** cortisol and blue-light gave links, seed-oils and raw-milk rendered empty |
| `tiktok.com/search?q=` | **Works** |
| `tiktok.com/tag/<hashtag>` | Renders, no video links, no wall. Recorded, not fought |
| A creator's profile grid | Renders, no video links. The bio reads fine, the grid is gated or lazy |

Ten links in about two minutes, no bot check on any route. Five videos scanned end to end with audio-only downloads (0.4 to 2.5 MB each, no video bytes), 9 to 14 s per download, 0.6 to 2.2 s per transcription, stored in `crawl/transcripts.db`. All five recorded as GPTZero skipped, no key on the machine.

**The catch:** only 1 of 5 transcripts is longer than GPTZero's 200-character minimum. Most discovered clips are short or music-heavy. The report counts "long enough and waiting on a key" separately so the denominator stays honest, and the crawl should favor longer talking videos. The pipeline's own verdict step is what decides which are false. This is a sample, not a census.

Two bugs found in the scan and fixed: `yt-dlp` sometimes exits non-zero while printing complete metadata, and the scanner trusted the exit code, so one video falsely showed as failed. It now trusts the JSON.

## What is in this folder

| File | Purpose |
|---|---|
| `resolver.py` | The full-text chain with the match guard and the three access states |
| `test_resolver.py` | Runs the chain on the eight blue-light studies, prints the coverage table |
| `fulltext_render.mjs` | Playwright renderer for free HTML pages that a plain fetch cannot read. Detects PDFs and hands them back as links |
| `paper_authorship.py` | GPTZero scoring of paper full text plus the SQLite database |
| `cite_and_scan.py` | Search, resolve, scan, store, in one command |
| `weigh.py` | The judging rules as a pure function: count both sides, weight by design and species, abstain when thin |
| `test_failure_modes.py` | 31 tests for logic, inputs, robustness and speed, with its own runner |
| `websearch_fallback.py` | Guideline and public-health web search when papers run thin, badged as web sources |
| `test_websearch_fallback.py`, `WIRING.md` | Its tests and where it slots into the backend |
| `crawl/` | Logged-out TikTok discovery scroller, audio-only transcript scan, report, and which routes work |

`fulltext_render.mjs` needs `playwright` installed. The frontend already has it as a dev dependency, so run it from there or `npm i playwright` in this folder.

## Porting into the backend

`resolve_fulltext()` slots into `Literature.paper()` in `app/literature.py` as the fallback after the existing Europe PMC XML fetch. `scan_paper()` and `store()` slot in next to `Detector.scan()` in `app/detection.py`, sharing its `Scan` and `Subclass` schemas. Add `free_needs_browser` to the `access_type` literal in `app/schemas.py`.
