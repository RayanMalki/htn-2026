"""
Voice stage: the plan's narration in, an audio file with word timings out, and every
scene's start and end moved to where the words actually land in that audio.

Engines, in order, chosen by what is available at run time:

  1. ElevenLabs when ELEVENLABS_API_KEY is set. Uses the with-timestamps endpoint,
     so word timings come straight from the engine and captions are exact.
     POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps
     header xi-api-key, body text, model_id, output_format. Response is JSON with
     audio_base64 and an alignment of characters with start and end seconds.
  2. Gemini when GEMINI_API_KEY is set, free of charge on Google's free tier.
     POST https://generativelanguage.googleapis.com/v1beta/interactions with the
     x-goog-api-key header, body model, input, response_format type audio and a
     speech_config voice. The reply carries base64 PCM at 24 kHz, 16 bit, mono
     under output_audio.data. Shape taken from the speech generation guide, not
     exercised here, there was no key on this machine.
  3. OpenAI when OPENAI_API_KEY is set. POST https://api.openai.com/v1/audio/speech
     with bearer auth, body model, input, voice, response_format, instructions.
     Returns raw audio bytes and no timestamps, so timings come from whisper or
     are estimated.
  4. macOS say, when the binary exists. A natural voice, written to aiff and
     converted to wav with ffmpeg.
  5. Silence of the estimated length, written with the standard library, so the
     pipeline and continuous integration never fail on a missing voice.

Network engines are cached by a hash of the engine name and the narration, in a
directory shared across cases. ElevenLabs' free tier is about a dozen renders a
month, so re-rendering the same script must never spend a second call. The engine
name is in the key so switching engines never serves the wrong file.

Word timings, in order: from the engine, else from whisper-cli on the rendered
audio (flags -ml 1 -sow give one segment per word, -oj writes them as JSON with
millisecond offsets), else estimated by spreading the words across the duration in
proportion to their length. plan.voice.timings_from records which one happened.

The evidence tags like [E3] are for the page, they are never spoken.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx

from app.video.plan import RenderPlan, Voice, Word

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
# A premade ElevenLabs voice. Override with ELEVENLABS_VOICE_ID, list yours at /v1/voices.
ELEVENLABS_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = "Kore"
GEMINI_RATE = 24000
OPENAI_URL = "https://api.openai.com/v1/audio/speech"
OPENAI_MODEL = "gpt-4o-mini-tts"
OPENAI_VOICE = "marin"
TONE = ("Scientific and direct, arguing against the video without sneering. "
        "Clear diction, steady pace, a short pause at each full stop.")
SAY_VOICES = ["Samantha", "Ava", "Zoe", "Allison", "Karen", "Daniel", "Moira", "Tessa", "Alex", "Fred"]
WORDS_PER_SECOND = 2.6
SAMPLE_RATE = 48000
DEFAULT_ENGINES = ["elevenlabs", "gemini", "openai", "macos_say", "silent"]
NETWORK_ENGINES = {"elevenlabs", "gemini", "openai"}
WHISPER_MODEL_CANDIDATES = [
    os.environ.get("WHISPER_MODEL", ""),
    "/Users/ezechielmiranda/conductor/workspaces/conductor-playground/dakar/grok-mvp/tools/test/ggml-base.en.bin",
]

_TAG = re.compile(r"\s*\[E\d+\]")


def spoken_text(plan: RenderPlan) -> str:
    """The narration with the evidence tags removed, one space between scenes."""
    parts = [_TAG.sub("", s.narration).strip() for s in plan.scenes if s.narration.strip()]
    return " ".join(p for p in parts if p)


def _run(args: list[str], timeout: float) -> bool:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _to_wav(src: Path, dst: Path) -> bool:
    """Any audio to 48 kHz mono 16-bit wav, the one format every later stage expects."""
    if not shutil.which("ffmpeg"):
        return False
    return _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                 "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)], timeout=120)


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return round(handle.getnframes() / float(handle.getframerate()), 3)
    except (wave.Error, OSError):
        return 0.0


def _write_silence(path: Path, seconds: float) -> None:
    frames = int(max(seconds, 0.1) * SAMPLE_RATE)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"\x00\x00" * frames)


# ----------------------------------------------------------------- engines

def _elevenlabs(text: str, out_dir: Path) -> tuple[Path, list[Word]] | None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", ELEVENLABS_DEFAULT_VOICE)
    try:
        response = httpx.post(
            ELEVENLABS_URL.format(voice_id=voice_id),
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": text, "model_id": ELEVENLABS_MODEL, "output_format": "mp3_44100_128"},
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        audio = base64.b64decode(body["audio_base64"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    mp3 = out_dir / "voice_elevenlabs.mp3"
    mp3.write_bytes(audio)
    wav = out_dir / "voice.wav"
    if not _to_wav(mp3, wav):
        return None
    return wav, _words_from_alignment(body.get("alignment") or body.get("normalized_alignment") or {})


def _words_from_alignment(alignment: dict) -> list[Word]:
    """Character timings to word timings: a word runs from its first character's start
    to its last character's end. Whitespace ends a word."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[Word] = []
    buf, w_start, w_end = "", None, None
    for ch, s, e in zip(chars, starts, ends, strict=False):
        if ch.isspace():
            if buf:
                words.append(Word(text=buf[:60], start=round(w_start, 3), end=round(w_end, 3)))
            buf, w_start, w_end = "", None, None
            continue
        if w_start is None:
            w_start = float(s)
        w_end = float(e)
        buf += ch
    if buf and w_start is not None:
        words.append(Word(text=buf[:60], start=round(w_start, 3), end=round(w_end, 3)))
    return words


def _openai(text: str, out_dir: Path) -> tuple[Path, list[Word]] | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        response = httpx.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": OPENAI_MODEL, "input": text, "voice": OPENAI_VOICE,
                  "response_format": "wav", "instructions": TONE},
            timeout=120,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    raw = out_dir / "voice_openai.wav"
    raw.write_bytes(response.content)
    wav = out_dir / "voice.wav"
    if not _to_wav(raw, wav):
        return None
    return wav, []


def _gemini(text: str, out_dir: Path) -> tuple[Path, list[Word]] | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        response = httpx.post(
            GEMINI_URL,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"model": GEMINI_MODEL, "input": f"{TONE} Read this: {text}",
                  "response_format": {"type": "audio"},
                  "generation_config": {"speech_config": [{"voice": GEMINI_VOICE}]}},
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        data = (body.get("output_audio") or {}).get("data") or _first_audio_data(body)
        if not data:
            return None
        audio = base64.b64decode(data)
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    wav = out_dir / "voice.wav"
    if audio[:4] == b"RIFF":
        raw = out_dir / "voice_gemini.wav"
        raw.write_bytes(audio)
        return (wav, []) if _to_wav(raw, wav) else None
    # Headerless PCM, tell ffmpeg what it is before converting.
    pcm = out_dir / "voice_gemini.pcm"
    pcm.write_bytes(audio)
    if not shutil.which("ffmpeg") or not _run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(GEMINI_RATE),
             "-ac", "1", "-i", str(pcm), "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
            timeout=120):
        return None
    return wav, []


def _first_audio_data(body) -> str | None:
    """Walk a response for the first base64 payload that sits under an audio-ish key.
    The documented path is output_audio.data, this is the safety net if it nests."""
    if isinstance(body, dict):
        for key, value in body.items():
            if "audio" in key.lower() and isinstance(value, dict) and isinstance(value.get("data"), str):
                return value["data"]
            found = _first_audio_data(value)
            if found:
                return found
    elif isinstance(body, list):
        for item in body:
            found = _first_audio_data(item)
            if found:
                return found
    return None


def _pick_say_voice() -> str | None:
    try:
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    installed = {line.split()[0] for line in listing.splitlines() if line.strip()}
    for name in SAY_VOICES:
        if name in installed:
            return name
    english = [line.split()[0] for line in listing.splitlines() if " en_" in line]
    return english[0] if english else None


def _macos_say(text: str, out_dir: Path) -> tuple[Path, list[Word]] | None:
    if platform.system() != "Darwin" or not shutil.which("say"):
        return None
    voice = _pick_say_voice()
    if not voice:
        return None
    aiff = out_dir / "voice_say.aiff"
    if not _run(["say", "-v", voice, "-r", "178", "-o", str(aiff), text], timeout=180):
        return None
    wav = out_dir / "voice.wav"
    if not _to_wav(aiff, wav):
        return None
    return wav, []


def _silent(text: str, out_dir: Path) -> tuple[Path, list[Word]]:
    wav = out_dir / "voice.wav"
    _write_silence(wav, len(text.split()) / WORDS_PER_SECOND)
    return wav, []


ENGINES = {"elevenlabs": _elevenlabs, "gemini": _gemini, "openai": _openai, "macos_say": _macos_say,
           "silent": _silent}


# ----------------------------------------------------------------- cache

def _cache_dir(out_dir: Path) -> Path:
    path = Path(os.environ.get("HYPECHECK_VOICE_CACHE", out_dir.parent / "voice_cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(engine: str, text: str) -> str:
    return hashlib.sha256(f"{engine}|{text}".encode()).hexdigest()[:20]


def _cache_get(engine: str, text: str, out_dir: Path) -> tuple[Path, list[Word], str] | None:
    """A cached render for this engine and exact narration, copied into out_dir."""
    base = _cache_dir(out_dir) / _cache_key(engine, text)
    wav, meta = base.with_suffix(".wav"), base.with_suffix(".json")
    if not (wav.exists() and meta.exists()):
        return None
    try:
        info = json.loads(meta.read_text())
        words = [Word.model_validate(w) for w in info.get("words", [])]
    except (OSError, ValueError):
        return None
    target = out_dir / "voice.wav"
    shutil.copyfile(wav, target)
    return target, words, info.get("timings_from", "none")


def _cache_put(engine: str, text: str, out_dir: Path, wav: Path, words: list[Word], timings_from: str) -> None:
    base = _cache_dir(out_dir) / _cache_key(engine, text)
    try:
        shutil.copyfile(wav, base.with_suffix(".wav"))
        base.with_suffix(".json").write_text(json.dumps({
            "engine": engine, "timings_from": timings_from, "words": [w.model_dump() for w in words]}))
    except OSError:
        pass


# ----------------------------------------------------------------- word timings

def _whisper_words(wav: Path, out_dir: Path) -> list[Word]:
    """whisper-cli with one word per segment. Returns [] when the tool or model is absent."""
    binary = shutil.which("whisper-cli")
    model = next((m for m in WHISPER_MODEL_CANDIDATES if m and Path(m).exists()), None)
    if not binary or not model or not shutil.which("ffmpeg"):
        return []
    wav16 = out_dir / "voice_16k.wav"
    if not _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                 "-ar", "16000", "-ac", "1", str(wav16)], timeout=60):
        return []
    prefix = out_dir / "voice_words"
    if not _run([binary, "-m", model, "-f", str(wav16), "-ml", "1", "-sow", "-oj", "-of", str(prefix),
                 "-nt", "-t", "4"], timeout=180):
        return []
    try:
        data = json.loads(Path(f"{prefix}.json").read_text())
    except (OSError, ValueError):
        return []
    words = []
    for seg in data.get("transcription", []):
        text = (seg.get("text") or "").strip()
        offsets = seg.get("offsets") or {}
        if not text or "from" not in offsets or "to" not in offsets:
            continue
        words.append(Word(text=text[:60], start=round(offsets["from"] / 1000, 3),
                          end=round(offsets["to"] / 1000, 3)))
    return words


def _estimated_words(text: str, duration: float) -> list[Word]:
    """Spread the script's words across the audio in proportion to their length, with a
    little extra weight on words that end a sentence, since a speaker pauses there."""
    tokens = text.split()
    if not tokens or duration <= 0:
        return []
    weights = [len(t) + (2.5 if t[-1] in ".!?" else 0.5 if t[-1] in ",;:" else 0) + 1 for t in tokens]
    unit = duration / sum(weights)
    words, t = [], 0.0
    for tok, w in zip(tokens, weights, strict=True):
        words.append(Word(text=tok[:60], start=round(t, 3), end=round(t + w * unit, 3)))
        t += w * unit
    words[-1].end = round(duration, 3)
    return words


def _align_to_script(script_words: list[str], timed: list[Word], duration: float) -> tuple[list[Word], str]:
    """Prefer the script's own words (they carry punctuation) with the engine's or
    whisper's timing. When the counts match, zip them. When they do not, keep the
    timed words as they are, since they are what was actually said."""
    if not timed:
        return _estimated_words(" ".join(script_words), duration), "estimated"
    if len(timed) == len(script_words):
        return [Word(text=s[:60], start=w.start, end=w.end) for s, w in zip(script_words, timed, strict=True)], "aligned"
    return timed, "asis"


# ----------------------------------------------------------------- scene timing

def _rescale_scenes(plan: RenderPlan, words: list[Word], duration: float) -> None:
    """Move every scene boundary to where its last word ends in the real audio. Falls
    back to scaling the estimates when the word count does not line up."""
    counts = [len(_TAG.sub("", s.narration).split()) for s in plan.scenes]
    if words and sum(counts) == len(words):
        t, index = 0.0, 0
        for scene, n in zip(plan.scenes, counts, strict=True):
            end = words[index + n - 1].end if n else t + 0.5
            index += n
            scene.start, scene.end = round(t, 3), round(end, 3)
            t = end
        plan.scenes[-1].end = round(duration, 3)
        return
    estimated_total = max((s.end for s in plan.scenes), default=0.0) or 1.0
    factor = duration / estimated_total
    for scene in plan.scenes:
        scene.start, scene.end = round(scene.start * factor, 3), round(scene.end * factor, 3)
    plan.scenes[-1].end = round(duration, 3)


def synthesize(plan: RenderPlan, out_dir: Path, engine_order: list[str] | None = None) -> RenderPlan:
    """Fill plan.voice and rescale the scenes. Never raises on a missing engine, the
    silent fallback always runs. engine_order narrows the engines tried, which is how
    tests exercise the silent path deterministically."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = spoken_text(plan)
    if not text:
        text = "No narration was produced for this case."

    audio, engine_words, engine, cached = None, [], "silent", None
    for name in engine_order or DEFAULT_ENGINES:
        fn = ENGINES.get(name)
        if not fn:
            continue
        if name in NETWORK_ENGINES and _engine_configured(name):
            hit = _cache_get(name, text, out_dir)
            if hit:
                audio, engine_words, engine, cached = hit[0], hit[1], name, hit[2]
                break
        got = fn(text, out_dir)
        if got:
            audio, engine_words, engine = got[0], got[1], name
            break
    if audio is None:
        audio, engine_words = _silent(text, out_dir)
        engine = "silent"

    duration = _wav_duration(audio)
    if duration <= 0:
        duration = round(len(text.split()) / WORDS_PER_SECOND, 3)

    script_words = text.split()
    if cached is not None:
        words, timings_from = engine_words, cached
        if not words:
            words, timings_from = _estimated_words(text, duration), "estimated"
    elif engine_words:
        words, _ = _align_to_script(script_words, engine_words, duration)
        timings_from = "engine"
    elif engine != "silent":
        whisper = _whisper_words(audio, out_dir)
        if whisper:
            words, _ = _align_to_script(script_words, whisper, duration)
            timings_from = "whisper"
        else:
            words, timings_from = _estimated_words(text, duration), "estimated"
    else:
        words, timings_from = _estimated_words(text, duration), "estimated"

    if engine in NETWORK_ENGINES and cached is None:
        _cache_put(engine, text, out_dir, audio, words, timings_from)

    plan.voice = Voice(audio_path=str(audio), duration=duration, engine=engine, words=words,
                       timings_from=timings_from)
    _rescale_scenes(plan, words, duration)
    plan.save(out_dir / "plan.json")
    return plan


def _engine_configured(name: str) -> bool:
    return bool(os.environ.get({"elevenlabs": "ELEVENLABS_API_KEY", "gemini": "GEMINI_API_KEY",
                                "openai": "OPENAI_API_KEY"}.get(name, "")))


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="hypecheck_voice_"))
