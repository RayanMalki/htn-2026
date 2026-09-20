"""The sole worker-facing video entry point."""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.media import run_process
from app.video.plan import atomic_text
from app.video.script import eligible_claims


class RenderError(RuntimeError):
    def __init__(self, message, code='render_failed'):
        super().__init__(message)
        self.code = code


def dependencies():
    from app.video.cards import CardsUnavailable, find_playwright
    checks = {name: bool(shutil.which(name)) for name in ('ffmpeg', 'ffprobe', 'node', 'whisper-cli')}
    checks['whisper_model'] = Path(settings().whisper_model).is_file()
    try:
        package = find_playwright(install=False)
        checks['playwright'] = True
        if checks['node']:
            result = subprocess.run(['node', '-e', "console.log(require(process.argv[1]).chromium.executablePath())",
                                     str(package)], capture_output=True, text=True, timeout=3)
            checks['chromium'] = result.returncode == 0 and Path(result.stdout.strip()).is_file()
        else:
            checks['chromium'] = False
    except (CardsUnavailable, OSError, subprocess.SubprocessError):
        checks['playwright'] = False
        checks['chromium'] = False
    checks['narration_configured'] = bool(settings().openai_api_key)
    return checks


async def render_video(case):
    from app.db import Case, read_case, session, update_case
    eligible_claims(case)
    cfg = settings()
    root = (cfg.media_root / case['id'] / 'video').resolve()
    root.mkdir(parents=True, exist_ok=True)
    atomic_text(root / 'input.json', json.dumps(case))
    for name in ['error.json', 'result.json', 'progress.json']:
        (root / name).unlink(missing_ok=True)
    options = case['result'].get('video', {}).get('options', {})
    args = [sys.executable, '-m', 'app.video.render', str(root / 'input.json'), str(root)]
    with session() as db:
        saved = db.get(Case, case['id'])
        if saved and saved.media_path and Path(saved.media_path).is_file():
            args += ['--source-clip', str(Path(saved.media_path).resolve())]
    if options.get('brainrot', False):
        args.append('--brainrot')
    if not options.get('sfx', True):
        args.append('--no-sfx')
    task = asyncio.create_task(run_process(*args, timeout=None))
    last = None
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.25)
            try:
                progress = json.loads((root / 'progress.json').read_text())
            except (OSError, ValueError):
                continue
            if progress != last:
                current = read_case(case['id'])['result'].get('video', {})
                update_case(case['id'], result_patch={'video': {**current, **progress, 'status': 'rendering'}})
                last = progress
        await task
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            failure = json.loads((root / 'error.json').read_text())
        except (OSError, ValueError):
            failure = {'message': 'Video rendering stopped or timed out. Retry to resume saved stages.',
                       'code': 'render_failed'}
        raise RenderError(failure['message'], failure['code']) from exc
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return {**json.loads((root / 'result.json').read_text()), 'options': options,
            'requested': case['result'].get('video', {}).get('requested', False)}
