"""Fault injection at every stage checks durable recovery without provider calls."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.video import render
from app.video.plan import Voice

EXAMPLE = Path(__file__).resolve().parents[1] / 'app/video/examples/blue_light_case.json'


@pytest.mark.parametrize('failed_stage', ['voice', 'cards', 'compose'])
def test_checkpoint_recovery_reuses_completed_stages(tmp_path, monkeypatch, failed_stage):
    from app.video import captions, cards, compose, post, voice
    calls = {name: 0 for name in ['voice', 'cards', 'compose', 'post', 'captions']}
    fail = [True]
    def stage(name):
        calls[name] += 1
        if name == failed_stage and fail[0]:
            fail[0] = False
            raise RuntimeError('interrupted')
    def voice_fn(plan, out):
        stage('voice')
        audio = out / 'voice.wav'
        audio.write_bytes(b'audio')
        plan.voice = Voice(audio_path=str(audio), duration=45, engine='openai')
        plan.scenes[-1].end = 45
        return plan
    def cards_fn(plan, out):
        stage('cards')
        for i, scene in enumerate(plan.scenes):
            target = out / f'card_{i}.png'
            target.write_bytes(b'card')
            scene.card_png = str(target)
        return plan
    def compose_fn(plan, out, **kwargs):
        stage('compose')
        target = out / 'composed.mp4'
        target.write_bytes(b'composed')
        plan.output_path = str(target)
        return plan
    def post_fn(plan, out):
        stage('post')
        return plan
    def overlay(plan, out, pages):
        stage('captions')
        target = out / 'response.mp4'
        target.write_bytes(b'final')
        plan.output_path = str(target)
        return plan
    monkeypatch.setattr(voice, 'synthesize', voice_fn)
    monkeypatch.setattr(cards, 'render_cards', cards_fn)
    monkeypatch.setattr(cards, 'render_caption_pages', lambda pages, *args: pages)
    monkeypatch.setattr(captions, 'pages', lambda plan: [])
    monkeypatch.setattr(compose, 'compose', compose_fn)
    monkeypatch.setattr(compose, 'overlay_captions', overlay)
    monkeypatch.setattr(post, 'apply', post_fn)
    monkeypatch.setattr(render, 'valid_media', lambda *args, **kw: True)
    monkeypatch.setattr(render, 'probe', lambda *args: {'format': {'duration': '45'},
                       'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}]})
    case = json.loads(EXAMPLE.read_text())
    with pytest.raises(RuntimeError, match='interrupted'):
        render.render_case(case, tmp_path)
    plan = render.render_case(case, tmp_path)
    assert plan.finding.label == 'contradicts'
    assert calls[failed_stage] == 2
    assert calls['compose'] == (2 if failed_stage == 'compose' else 1)
    assert calls['post'] == calls['captions'] == 0
    before = calls.copy()
    render.render_case(case, tmp_path)
    assert before == calls
    # Corrupting final output only repeats the final stage, not paid voice generation.
    Path(plan.output_path).write_bytes(b'corrupt')
    render.render_case(case, tmp_path)
    assert calls['voice'] == before['voice']
    assert calls['voice'] == before['voice']
    assert calls['compose'] == before['compose']


def test_api_has_one_video_route_and_manual_render_is_queued(client, case_id, passage, monkeypatch):
    from app.db import read_case, update_case
    from app.main import app
    from app.schemas import Claim
    claim = Claim(id='c1', text='Vitamin C prevents colds.', start=0, end=1, search_terms=['vitamin C'])
    assert client.post(f'/api/cases/{case_id}/render').status_code == 409
    update_case(case_id, status='complete', result_patch={'model_mode': 'live',
        'analysis': {'claims': [claim.model_dump()]}, 'claims': {'c1': {'claim': claim.model_dump(),
        'status': 'complete', 'evidence': [passage.model_dump()], 'verdict': {'label': 'contradicts',
        'explanation': 'The review did not find prevention.', 'limitations': [],
        'citations': [{'passage_id': passage.id, 'quote': passage.text}]}}}})
    enqueue = Mock()
    monkeypatch.setattr('app.main.enqueue', enqueue)
    for _ in range(2):
        assert client.post(f'/api/cases/{case_id}/render?brainrot=true&sfx=false').status_code == 202
    enqueue.assert_called_once_with(case_id)
    video = read_case(case_id)['result']['video']
    assert video['options'] == {'brainrot': True, 'sfx': False}
    assert video['requested'] is True
    assert len([r for r in app.routes if getattr(r, 'path', '') == '/api/cases/{case_id}/video'
                and 'GET' in getattr(r, 'methods', set())]) == 1
    assert client.get(f'/api/cases/{case_id}/video').status_code == 409


async def test_render_process_cancellation_is_awaited(case_id, passage, monkeypatch):
    import asyncio

    from app.db import read_case, update_case
    from app.video import render_video
    from app.video.script import eligible_claims
    case = json.loads(EXAMPLE.read_text())
    case['id'] = case_id
    eligible_claims(case)
    update_case(case_id, result_patch=case['result'])
    cancelled = asyncio.Event()
    started = asyncio.Event()
    async def process(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr('app.video.run_process', process)
    task = asyncio.create_task(render_video(read_case(case_id)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


async def test_cancel_kills_detached_descendants(tmp_path):
    import asyncio
    import sys

    import psutil

    from app.media import run_process
    pidfile = tmp_path / 'child.pid'
    code = ('import subprocess,sys,time,pathlib; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True); '
            'pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)')
    task = asyncio.create_task(run_process(sys.executable, '-c', code, str(pidfile), timeout=10))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.02)
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(50):
        if not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            break
        await asyncio.sleep(0.02)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_legacy_artifacts_are_readable_but_legacy_paths_are_not_served(client, case_id, tmp_path):
    from app.config import settings
    from app.db import update_case
    artifact = 'a' * 20
    folder = settings().media_root / case_id / 'video' / artifact
    folder.mkdir(parents=True)
    (folder / 'response.mp4').write_bytes(b'version-two-artifact')
    update_case(case_id, status='complete', result_patch={'video': {'version': 2, 'status': 'ready', 'artifact': artifact}})
    assert client.get(f'/api/cases/{case_id}/video').content == b'version-two-artifact'
    private = tmp_path / 'private.txt'
    private.write_text('must not be served')
    update_case(case_id, result_patch={'video': {}, 'render': {'status': 'done', 'path': str(private)}})
    assert client.get(f'/api/cases/{case_id}/video').status_code == 409
