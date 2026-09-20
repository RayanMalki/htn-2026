"""OpenAI narration, durable audio cache, and local word alignment."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import settings
from app.video.plan import Voice, Word, atomic_text
from app.video.runtime import concat_line, ff, probe, valid_media
from app.video.script import ScriptBudgetError

TONE = 'Read the supplied text exactly, clearly and calmly as an evidence explainer. Do not add words.'
SAMPLE_RATE = 48000


class NarrationError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _model_hash(path, size, modified):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alignment_identity():
    model = Path(settings().whisper_model)
    if not model.is_file():
        return ['whisper.cpp-v1.7.6', 'unavailable']
    stat = model.stat()
    return ['whisper.cpp-v1.7.6', _model_hash(str(model), stat.st_size, stat.st_mtime_ns)]


def _cache_key(engine, text):
    cfg = settings()
    return hashlib.sha256(json.dumps([3, engine, cfg.tts_model, cfg.tts_voice, TONE, text]).encode()).hexdigest()[:20]


def _estimated_words(text, duration):
    tokens = text.split()
    weights = [len(t) + 2 for t in tokens]
    unit = duration / max(sum(weights), 1)
    words, t = [], 0.0
    for tok, weight in zip(tokens, weights, strict=True):
        words.append(Word(text=tok, start=t, end=t + weight * unit))
        t += weight * unit
    return words


def _whisper_words(wav, out_dir):
    binary = shutil.which('whisper-cli')
    model = settings().whisper_model
    if not binary or not Path(model).is_file():
        return []
    wav16 = out_dir / 'align.wav'
    ff(['-i', str(wav), '-ar', '16000', '-ac', '1', str(wav16)], timeout=10)
    prefix = out_dir / 'words'
    proc = subprocess.run([binary, '-m', model, '-f', str(wav16), '-ml', '1', '-sow', '-oj',
                           '-of', str(prefix), '-t', '2'], capture_output=True, timeout=30)
    if proc.returncode:
        return []
    data = json.loads(prefix.with_suffix('.json').read_text())
    return [Word(text=s['text'].strip(), start=s['offsets']['from'] / 1000, end=s['offsets']['to'] / 1000)
            for s in data.get('transcription', []) if s.get('text', '').strip()]


def valid_words(text, words, duration):
    def normalized(value):
        return re.sub(r'[^\w]', '', value).lower()
    expected = text.split()
    return (bool(words) and len(words) == len(expected) and all(
        normalized(w.text) == normalized(token) and 0 <= w.start < w.end <= duration + 0.05
        for w, token in zip(words, expected, strict=True))
        and all(a.end <= b.start + 0.02 for a, b in zip(words, words[1:], strict=False)))


def aligned_words(text, audio, out_dir, duration):
    try:
        words = _whisper_words(audio, out_dir)
        if valid_words(text, words, duration):
            return [Word(text=t, start=w.start, end=min(w.end, duration))
                    for t, w in zip(text.split(), words, strict=True)], 'whisper'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    return _estimated_words(text, duration), 'estimated'


def speech(text, output):
    cfg = settings()
    if not cfg.openai_api_key:
        raise NarrationError('OpenAI narration is not configured. Add OPENAI_API_KEY and retry.')
    try:
        response = httpx.post('https://api.openai.com/v1/audio/speech',
                              headers={'Authorization': f'Bearer {cfg.openai_api_key}'},
                              json={'model': cfg.tts_model, 'voice': cfg.tts_voice, 'input': text,
                                    'instructions': TONE, 'response_format': 'wav'}, timeout=35)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 429):
            raise NarrationError('OpenAI rejected narration. Check access, credits or rate limits, then retry.') from None
        raise NarrationError('OpenAI narration failed. Retry when the provider is available.') from None
    except httpx.HTTPError:
        raise NarrationError('OpenAI narration timed out or could not connect. Retry to resume.') from None
    temporary = output.with_suffix('.part.wav')
    temporary.write_bytes(response.content)
    if not valid_media(temporary):
        raise NarrationError('OpenAI returned invalid audio. Retry narration.')
    temporary.replace(output)


def synthesize(plan, out_dir, engine_order=None):
    """Audio is checkpointed BEFORE alignment. Explicit silence is for fixtures only."""
    silent = engine_order == ['silent']
    cache = Path(os.environ.get('HYPECHECK_VOICE_CACHE', out_dir.parent / 'voice_cache'))
    cache.mkdir(parents=True, exist_ok=True)
    pieces = []
    for i, scene in enumerate(plan.scenes):
        if scene.narration:
            engine = 'silent' if silent else 'openai'
            folder = cache / _cache_key(engine, scene.narration)
            folder.mkdir(parents=True, exist_ok=True)
            audio = folder / 'audio.wav'
            if not valid_media(audio):
                if silent:
                    ff(['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t',
                        str(max(1, len(scene.narration.split()) / 2.6)), str(audio)])
                else:
                    speech(scene.narration, audio)
            duration = float(probe(audio)['format']['duration'])
            timing = folder / 'timing.json'
            identity = [hashlib.sha256(audio.read_bytes()).hexdigest(), alignment_identity()]
            try:
                info = json.loads(timing.read_text())
                cached_words = [Word.model_validate(w) for w in info['words']]
                if not valid_words(scene.narration, cached_words, duration) or info.get('mode') not in {'whisper', 'estimated'}:
                    info = {}
            except (OSError, ValueError, KeyError, TypeError):
                info = {}
            if info.get('identity') != identity:
                words, mode = aligned_words(scene.narration, audio, folder, duration)
                info = {'identity': identity, 'words': [w.model_dump() for w in words], 'mode': mode}
                atomic_text(timing, json.dumps(info))
            words = [Word.model_validate(w) for w in info['words']]
            pieces.append((scene, audio, duration, words, info['mode']))
        elif scene.kind == 'clip':
            audio = out_dir / 'source_audio.wav'
            if not valid_media(audio, duration=plan.source_duration):
                ff(['-ss', str(plan.source_start), '-i', plan.source_clip, '-t', str(plan.source_duration),
                    '-vn', '-ar', '48000', '-ac', '1', str(audio)])
            pieces.append((scene, audio, plan.source_duration, [], 'none'))
        else:
            pieces.append((scene, None, scene.end - scene.start, [], 'none'))
    total = sum(p[2] for p in pieces)
    if total > 60:
        pieces = [p for p in pieces if p[0].kind != 'paper']
        total = sum(p[2] for p in pieces)
    if total > 60:
        raise ScriptBudgetError('Spoken findings and limitations exceed 60 seconds. Essential content was preserved.')
    plan.scenes = [p[0] for p in pieces]
    pad = max(0, 45 - total)
    # Give spare time to reading evidence before holding the closing card.
    for i, piece in enumerate(pieces):
        scene, audio, duration, words, mode = piece
        if scene.kind == 'paper' and pad > 0:
            extra = min(8, pad)
            pieces[i] = (scene, audio, duration + extra, words, mode)
            pad -= extra
    tracks, all_words, modes, cursor = [], [], [], 0.0
    for i, (scene, audio, duration, words, mode) in enumerate(pieces):
        length = duration + (pad if i == len(pieces) - 1 else 0)
        output = out_dir / f'audio_{i}.wav'
        if audio:
            ff(['-i', str(audio), '-af', 'apad', '-t', str(length), '-ar', '48000', '-ac', '1', str(output)])
        else:
            ff(['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', str(length), str(output)])
        scene.start, scene.end = cursor, cursor + length
        all_words.extend(Word(text=w.text, start=cursor + w.start, end=cursor + w.end) for w in words)
        if words:
            modes.append(mode)
        cursor += length
        tracks.append(output)
    listing = out_dir / 'audio.ffconcat'
    atomic_text(listing, '\n'.join(concat_line(p) for p in tracks))
    output = out_dir / 'voice.wav'
    ff(['-f', 'concat', '-safe', '0', '-i', str(listing), '-c:a', 'pcm_s16le', str(output)])
    plan.voice = Voice(audio_path=str(output), duration=cursor, engine='silent' if silent else 'openai',
                       words=all_words, timings_from='whisper' if modes and set(modes) == {'whisper'} else 'estimated')
    plan.save(out_dir / 'plan.json')
    return plan
