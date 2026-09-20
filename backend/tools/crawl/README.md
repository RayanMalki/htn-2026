# TikTok discovery crawl and transcript scan

Find health videos on TikTok without logging in, pull their audio, transcribe locally, and score the transcripts with GPTZero. This is the investigative half of the GPTZero track ("scan a significant source for AI slop") and it feeds the leaderboard. The pipeline's own verdict step decides which claims are supported, contradicted or uncertain. This folder only builds the sample and the scan.

## Run

```
# 1. collect video links, one headed muted browser, human pacing, cap 30
node scroll_tiktok.mjs --cap 30

# 2. metadata, audio only download, local transcript, GPTZero (skipped without a key)
GPTZERO_API_KEY=... python3 scan_batch.py --limit 30

# 3. what is in the database and the AI-written share
python3 report.py
```

`scroll_tiktok.mjs` appends to `urls.jsonl` and never re-adds a link it has seen. `scan_batch.py` skips any URL already in `transcripts.db`, so both are safe to rerun. To rescore transcripts after you get a key, clear their status first:

```
sqlite3 transcripts.db "UPDATE transcripts SET gptzero_status=NULL WHERE gptzero_status='skipped'"
```

## Dependencies and paths

This crawler is experimental and separate from the app's video pipeline. The results
below are historical samples, not current live acceptance.

From the repository root, install Python requirements as described in the main README,
then install the locked browser runtime:

```sh
npm ci --prefix backend/app/video
node backend/app/video/node_modules/playwright/cli.js install chromium
export PATH="$PWD/.venv/bin:$PATH"
export WHISPER_MODEL=/absolute/path/to/ggml-base.en.bin
cd backend/tools/crawl
```

Install FFmpeg and `whisper-cli` on PATH. The renderer Docker build records the pinned
Whisper runtime/model versions. `YTDLP_BIN` optionally selects another yt-dlp executable;
it otherwise uses PATH. The crawler's browser-impersonation mode additionally needs
`curl_cffi` in the Python environment running yt-dlp; it is not a core app dependency.
`HYPECHECK_PLAYWRIGHT_DIR` can select another installed Playwright directory.
No sibling developer checkout is required. Set `PLAYWRIGHT_BROWSERS_PATH` if Chromium
was installed into a custom location. Run the three commands above from this directory.

## What each discovery route did, logged out, Saturday Sept 19

| Route | Example | Result |
|---|---|---|
| `tiktok.com/discover/<topic>` | `/discover/cortisol`, `/discover/blue-light` | **Works.** Rendered and gave video links. `seed-oils` and `raw-milk` rendered but showed no links, those topic pages seem to be empty or a different layout |
| `tiktok.com/search?q=<terms>` | `seed oils inflammation`, `raw milk benefits` | **Works.** Rendered and gave video links on both queries tried |
| `tiktok.com/tag/<hashtag>` | `/tag/seedoils`, `/tag/cortisol` | Rendered, **no video links** on any of four tags. No wall text either. The grid likely loads behind a login prompt or through a request the logged out page does not make. Recorded, not fought |
| `tiktok.com/@<profile>` | `@dr_idz` | Rendered, **no video links** in the anchor pattern the scroller looks for. The bio and follower count do render (proven separately today), so the video grid is what is gated or lazy loaded. Recorded, not fought |

The one test run collected 10 links from discover and search in about 2 minutes. Nothing hit a bot check. The cap and the 1.5 to 4 second scroll jitter are deliberate: this is a sample from the user's own connection, not a scrape.

## Scan results from the test

Five of the ten collected, no GPTZero key on the machine:

| Video | Views | Length | Transcript | Download | Transcribe |
|---|---|---|---|---|---|
| `@welly.cipes` | 8.2M | 11 s | 59 chars | 9.0 s | 0.8 s |
| `@zopp_5` | 5.6M | 13 s | 13 chars | 14.0 s | 0.6 s |
| `@goldenjaguar6_` | 2.6M | 20 s | 178 chars | 9.1 s | 1.1 s |
| `@britbox` | 2.4M | 91 s | 695 chars | 8.9 s | 2.2 s |
| `@gu_rados` | 165K | 15 s | 7 chars | 8.9 s | 0.6 s |

Download is 9 to 14 seconds per video on this connection and is the whole wait. Transcription is 1 to 2 seconds. Every transcript was stored with GPTZero status `skipped`, as expected with no key.

One bug came out of this run: `@gu_rados` first showed as "metadata failed" because `yt-dlp` exited non-zero while still printing a complete metadata object, and the scanner trusted the exit code over the output. It now trusts the JSON. The rerun scanned it fine.

**A caveat the numbers make obvious:** most discovered clips are short or music heavy and produce transcripts under GPTZero's 200 character minimum. Only 1 of the 5 here is long enough to score. The crawl should favor longer talking videos, and the report counts "long enough and waiting on a key" separately so the denominator is honest.

## Pacing rules, built in

- One browser session for the whole scroll, headed, muted, no login, no cookies, no stealth flags. Headed is used because today a headed browser passed automatic checks that block headless, with nothing added to fight them.
- Scroll pauses jittered 1.5 to 4 seconds. Downloads spaced 3 to 8 seconds. Cap 30 per run.
- Audio only. `yt-dlp -x` keeps the audio stream and discards the video bytes.
- When a page shows a wall it is recorded in `routes.json` and the next route is tried. Nothing retries a wall.

## Honest caveats

- **Logged out, so this is a sample, not a census.** Logged out TikTok shows what it chooses to show. The share of AI written transcripts in this database is the share in what we could see, and the writeup should say so.
- **GPTZero on spoken transcripts is less reliable than on written prose.** Its detector is trained on written text. A transcript of someone talking reads differently, and the team's transcript detector already measured that fillers do not change the classification. Treat the video description and any on screen text as the higher confidence signals and the transcript as the lower one.
- **This does not decide what is false.** It finds videos and scores how they were written. The evidence pipeline reads the papers and produces the verdict.
- **The tag and profile routes are recorded as not working logged out.** If they matter, the fix is a different discovery route, not a login.

## Files

| File | Purpose |
|---|---|
| `scroll_tiktok.mjs` | Discovery scroller, writes `urls.jsonl` and `routes.json` |
| `scan_batch.py` | Metadata, audio, transcript, GPTZero, into `transcripts.db` |
| `report.py` | The table and the AI written share |
| `urls.jsonl` | Collected links with the route that found each |
| `routes.json` | What every route returned on the last run |
| `transcripts.db` | The database, SQLite |
| `audio/` | Audio only files, one per scanned video |
