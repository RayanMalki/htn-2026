"""
Scan every collected TikTok: metadata, audio only download, local transcript,
then GPTZero on the transcript. Results go to crawl/transcripts.db and the run
is idempotent, so rerunning only touches videos not yet in the database.

Pacing is deliberate. Downloads are spaced 3 to 8 seconds apart with jitter,
because this runs on the user's own connection and the whole point is a sample,
not a scrape. Audio only, never video, the user does not want bandwidth spent.

GPTZero is called only when GPTZERO_API_KEY is set. Without it every transcript
is stored with status skipped and can be scored later by rerunning with the key.

Usage:
    python3 scan_batch.py [--limit 5] [--urls urls.jsonl]
"""

import json
import os
import random
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))

from paper_authorship import MAXIMUM_CHARACTERS, MINIMUM_CHARACTERS, _predict, read_scan  # noqa: E402

YTDLP = TOOLS / ".venv" / "bin" / "yt-dlp"
WHISPER_MODEL = TOOLS / "test" / "ggml-base.en.bin"
DB_PATH = HERE / "transcripts.db"
AUDIO_DIR = HERE / "audio"
IMPERSONATE = ["chrome-136", "chrome-131:android"]


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            url TEXT PRIMARY KEY,
            author TEXT,
            description TEXT,
            views INTEGER,
            likes INTEGER,
            duration REAL,
            route TEXT,
            transcript TEXT,
            transcript_chars INTEGER,
            gptzero_status TEXT,
            ai_probability REAL,
            document_classification TEXT,
            subclass TEXT,
            scanned_at TEXT,
            notes TEXT
        )
    """)
    return conn


def run(cmd: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def metadata(url: str) -> tuple[dict | None, str]:
    """yt-dlp metadata with the impersonation fallback that worked today."""
    for imp in IMPERSONATE:
        out = run([str(YTDLP), "--impersonate", imp, "--dump-single-json", "--skip-download", "--no-warnings", url])
        # Trust the JSON, not the exit code. yt-dlp can exit non-zero over a format
        # or post-processing complaint and still print a complete metadata object.
        # Requiring returncode 0 threw away a perfectly good record in testing.
        if out.stdout.strip():
            try:
                return json.loads(out.stdout), imp
            except json.JSONDecodeError:
                pass
    return None, "metadata failed on every identity"


def download_audio(url: str, video_id: str, imp: str) -> Path | None:
    """Audio only. -x extracts the audio stream, no video bytes are kept."""
    AUDIO_DIR.mkdir(exist_ok=True)
    target = AUDIO_DIR / f"{video_id}.m4a"
    if target.exists():
        return target
    out = run([str(YTDLP), "--impersonate", imp, "-f", "bestaudio/best", "-x", "--audio-format", "m4a",
               "--sleep-requests", "2", "--no-warnings", "-o", str(AUDIO_DIR / f"{video_id}.%(ext)s"), url], timeout=180)
    if out.returncode != 0:
        return None
    return target if target.exists() else next(AUDIO_DIR.glob(f"{video_id}.*"), None)


def transcribe(audio: Path) -> str:
    wav = audio.with_suffix(".wav")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", str(wav)])
    out = run(["whisper-cli", "-m", str(WHISPER_MODEL), "-f", str(wav), "-nt", "-t", "4"], timeout=300)
    wav.unlink(missing_ok=True)
    return " ".join(out.stdout.split())


def gptzero(text: str, api_key: str | None) -> dict:
    """Same request and parsing as the paper scanner, so the two databases agree."""
    if not api_key:
        return {"status": "skipped", "note": "GPTZERO_API_KEY is not configured."}
    text = text[:MAXIMUM_CHARACTERS]
    if len(text) < MINIMUM_CHARACTERS:
        return {"status": "skipped", "note": f"Transcript is {len(text)} characters, at least {MINIMUM_CHARACTERS} needed."}
    try:
        scan = read_scan("transcript", _predict(text, api_key), len(text))
    except Exception as exc:  # noqa: BLE001 - a detector failure never fails the row
        return {"status": "unavailable", "note": str(exc)[:120]}
    return {
        "status": "scored",
        "ai_probability": scan.ai_probability,
        "document_classification": scan.document_classification,
        "subclass": (f"{scan.subclass.kind}:{scan.subclass.predicted_class}" if scan.subclass else None),
        "note": scan.summary,
    }


def main() -> None:
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 30
    urls_path = Path(args[args.index("--urls") + 1]) if "--urls" in args else HERE / "urls.jsonl"
    api_key = os.environ.get("GPTZERO_API_KEY")
    if not api_key:
        print("GPTZERO_API_KEY is not set, transcripts will be stored as skipped and can be scored later.")

    conn = db()
    done = {r[0] for r in conn.execute("SELECT url FROM transcripts")}
    queue = []
    for line in urls_path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item["url"] not in done:
            queue.append(item)
    queue = queue[:limit]
    print(f"{len(queue)} videos to scan, {len(done)} already in the database\n")

    for i, item in enumerate(queue, start=1):
        url = item["url"]
        # The scroller records the handle as it appears in the link, with the @.
        # yt-dlp's uploader field has no @. Store one shape so the report prints one @.
        item["author"] = (item.get("author") or "").lstrip("@")
        t0 = time.time()
        meta, imp = metadata(url)
        if not meta:
            conn.execute("INSERT OR REPLACE INTO transcripts (url, author, route, gptzero_status, scanned_at, notes) VALUES (?,?,?,?,?,?)",
                         (url, item.get("author"), item.get("route"), "skipped", datetime.now(UTC).isoformat(), imp))
            conn.commit()
            print(f"[{i}/{len(queue)}] metadata failed  {url}")
            continue
        video_id = str(meta.get("id") or url.rsplit("/", 1)[-1])
        audio = download_audio(url, video_id, imp)
        if not audio:
            conn.execute("INSERT OR REPLACE INTO transcripts (url, author, description, views, likes, duration, route, gptzero_status, scanned_at, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (url, meta.get("uploader"), (meta.get("description") or "")[:500], meta.get("view_count"), meta.get("like_count"),
                          meta.get("duration"), item.get("route"), "skipped", datetime.now(UTC).isoformat(), "audio download failed"))
            conn.commit()
            print(f"[{i}/{len(queue)}] audio failed     {url}")
            continue
        t_dl = time.time() - t0
        text = transcribe(audio)
        t_tx = time.time() - t0 - t_dl
        result = gptzero(text, api_key)
        conn.execute("""
            INSERT OR REPLACE INTO transcripts
            (url, author, description, views, likes, duration, route, transcript, transcript_chars,
             gptzero_status, ai_probability, document_classification, subclass, scanned_at, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (url, meta.get("uploader"), (meta.get("description") or "")[:500], meta.get("view_count"), meta.get("like_count"),
              meta.get("duration"), item.get("route"), text, len(text), result["status"], result.get("ai_probability"),
              result.get("document_classification"), result.get("subclass"), datetime.now(UTC).isoformat(), result.get("note")))
        conn.commit()
        print(f"[{i}/{len(queue)}] @{(meta.get('uploader') or '?')[:18]:18} {meta.get('duration') or 0:>4.0f}s  "
              f"{len(text):>5} chars  dl {t_dl:4.1f}s  tx {t_tx:4.1f}s  gptzero {result['status']}")
        if i < len(queue):
            time.sleep(random.uniform(3, 8))
    conn.close()


if __name__ == "__main__":
    main()
