"""Bounded media helpers. The worker owns and cancels the complete process group."""
import json
import math
import subprocess
from pathlib import Path


def probe(path):
    proc = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                          capture_output=True, text=True, check=True, timeout=8)
    return json.loads(proc.stdout)


def valid_media(path, *, video=False, duration=None, size=None):
    try:
        info = probe(path)
        seconds = float(info['format']['duration'])
        if not math.isfinite(seconds) or seconds <= 0:
            return False
        if duration is not None and abs(seconds - duration) > 0.25:
            return False
        if video:
            stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
            if duration is not None and abs(float(stream.get('duration', seconds)) - duration) > 0.25:
                return False
            if size and (stream['width'], stream['height']) != size:
                return False
        else:
            next(s for s in info['streams'] if s['codec_type'] == 'audio')
        return True
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        return False


def ff(args, timeout=None):
    """Only complete, decodable output files are promoted to their checkpoint names."""
    target = Path(args[-1])
    temporary = target.with_name(target.stem + '.part' + target.suffix)
    proc = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                           '-filter_complex_threads', '1', *args[:-1], str(temporary)],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError('Media encoding failed; retry this render.')
    probe(temporary)
    temporary.replace(target)


def concat_line(path):
    # ffconcat uses its own quoting, not shell quoting.
    return "file '" + str(Path(path).resolve()).replace("'", "'\\''") + "'"
