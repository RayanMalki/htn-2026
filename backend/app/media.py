import asyncio
import json
import math
import os
import signal
import socket
import sys
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings

MAX_BYTES = 100 * 1024 * 1024


class MediaError(Exception):
    pass


async def run_process(*args: str, timeout: float):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        raise
    if proc.returncode:
        raise MediaError("Media processing failed")
    return stdout


async def download(case_id: str, source_url: str) -> Path:
    # The URL itself is canonicalized by CaseCreate; do not accept arbitrary downloader URLs.
    from app.schemas import CaseCreate
    source_url = CaseCreate(source_url=source_url).source_url
    addresses = await asyncio.to_thread(socket.getaddrinfo, urlsplit(source_url).hostname, 443)
    if not addresses or any(not ip_address(entry[4][0]).is_global for entry in addresses):
        raise MediaError("Video host resolved to a non-public address")
    folder = settings().media_root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("source.*"):
        old.unlink(missing_ok=True)
    try:
        await run_process(
            sys.executable, "-m", "app.downloader", "--ignore-config", "--no-playlist", "--no-warnings", "--no-progress",
            "--socket-timeout", "5", "--retries", "0", "--fragment-retries", "0",
            "--max-filesize", str(MAX_BYTES), "--match-filters", "duration <= 100",
            "--hls-prefer-native", "--merge-output-format", "mp4",
            "-f", "best[height<=720]/bestvideo[height<=720]+bestaudio/best", "-o", str(folder / "source.%(ext)s"), source_url,
            timeout=15,
        )
    except (TimeoutError, OSError, MediaError) as exc:
        for partial in folder.glob("source.*"):
            partial.unlink(missing_ok=True)
        raise MediaError("Video download unavailable. Upload the clip to continue.") from exc
    files = [p for p in folder.glob("source.*") if p.suffix not in {".part", ".ytdl"}]
    if len(files) != 1 or files[0].stat().st_size > MAX_BYTES:
        raise MediaError("No supported video was downloaded. Upload the clip to continue.")
    return files[0]


async def extract_audio(path: Path) -> tuple[Path, float]:
    if not path.exists() or path.stat().st_size > MAX_BYTES:
        raise MediaError("The video is missing or exceeds 100 MB")
    raw = await run_process(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format",
        "-show_streams", "-of", "json", str(path), timeout=5,
    )
    try:
        probe = json.loads(raw)
        duration = float(probe["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise MediaError("Cannot determine video duration") from exc
    if not math.isfinite(duration) or not 0 < duration <= 100:
        raise MediaError("Use a video no longer than 100 seconds")
    if not any(s.get("codec_type") == "video" for s in probe.get("streams", [])):
        raise MediaError("Upload a video file")
    if not any(s.get("codec_type") == "audio" for s in probe.get("streams", [])):
        raise MediaError("This clip has no audio. Spoken English is required in iteration one.")
    output = path.parent / "audio.mp3"
    await run_process(
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "48k", "-t", "100", str(output), timeout=10,
    )
    return output, duration
