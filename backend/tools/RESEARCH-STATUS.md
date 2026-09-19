# Where we are: reading papers, reasoning on them, seeing videos

Written Saturday Sept 19, 5:30 PM, during the code window. Everything below was measured on real papers and a real video today, not estimated.

## 1. Reading full papers

**Status: working, 3 of 8 landmark papers fully readable, up from 1 of 8 this morning.**

The original backend (`app/literature.py`) reads full text only for papers that are open access inside PubMed Central. On the eight studies the blue-light creator cited on screen, that reached exactly one. Today's resolver (`resolver.py`) adds three layers and was tested against those same eight:

| Study | Before | After | Route |
|---|---|---|---|
| Brainard 2001 | abstract | **full text, 67,448 chars** | Europe PMC's own free-link list |
| Chinoy 2018 | full text | full text, 69,187 chars | Europe PMC XML (already worked) |
| Gooley 2010 | abstract | **full text, 83,841 chars** | DOI link in Europe PMC's list |
| Thapan 2001 | abstract | free, needs a human click | Unpaywall found it, page is bot-gated |
| West 2011 | abstract | free, needs a human click | Legacy domain dead, current one bot-gated |
| Figueiro 2011 | abstract | abstract | No DOI, no free copy anywhere |
| Wood 2013 | abstract | abstract | Genuinely paywalled |
| Cajochen 2011 | abstract | abstract | Genuinely paywalled |

**The three access states the page must show**, because collapsing them is dishonest:

- `full_text`: the machine read the whole paper.
- `free_needs_browser`: a free copy exists, a person clicking the link gets it, a script cannot. Show the link. This is not "paywalled."
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

## What is in this folder

| File | Purpose |
|---|---|
| `resolver.py` | The full-text chain with the match guard and the three access states |
| `test_resolver.py` | Runs the chain on the eight blue-light studies, prints the coverage table |
| `fulltext_render.mjs` | Playwright renderer for free HTML pages that a plain fetch cannot read. Detects PDFs and hands them back as links |
| `paper_authorship.py` | GPTZero scoring of paper full text plus the SQLite database |
| `cite_and_scan.py` | Search, resolve, scan, store, in one command |

`fulltext_render.mjs` needs `playwright` installed. The frontend already has it as a dev dependency, so run it from there or `npm i playwright` in this folder.

## Porting into the backend

`resolve_fulltext()` slots into `Literature.paper()` in `app/literature.py` as the fallback after the existing Europe PMC XML fetch. `scan_paper()` and `store()` slot in next to `Detector.scan()` in `app/detection.py`, sharing its `Scan` and `Subclass` schemas. Add `free_needs_browser` to the `access_type` literal in `app/schemas.py`.
