import shutil
from unittest.mock import Mock

import pytest

from app.config import settings
from app.db import read_case, update_case
from app.schemas import Citation, Claim, Verdict
from app.video.render import render_case
from app.video.runtime import ff, probe
from app.video.script import build_plan


def ready_case(case_id, passage):
    claim = Claim(id='c1', text='Vitamin C prevents colds.', start=0, end=1, search_terms=['vitamin C'])
    verdict = Verdict(label='contradicts', explanation='The review did not find prevention.',
                      citations=[Citation(passage_id=passage.id, quote=passage.text)], limitations=['Abstract only.'])
    return update_case(case_id, status='complete', result_patch={
        'model_mode': 'live', 'analysis': {'claims': [claim.model_dump()], 'omitted_claims': 1},
        'claims': {'c1': {'status': 'complete', 'claim': claim.model_dump(),
                          'verdict': verdict.model_dump(), 'evidence': [passage.model_dump()]}}})


def test_storyboard_requires_validated_complete_live_verdicts(case_id, passage, tmp_path):
    case = ready_case(case_id, passage)
    plan = build_plan(case, tmp_path)
    scenes, sources = [s.model_dump() for s in plan.scenes], [s.model_dump() for s in plan.evidence]
    assert sources[0]['quote'] == passage.text
    assert sources[0]['url'] == passage.source_url
    assert any('Abstract only.' == scene['narration'] for scene in scenes)
    assert '1 additional claim' in scenes[-1]['narration']
    case['result']['claims']['c1']['verdict']['citations'][0]['quote'] = 'Invented'
    with pytest.raises(ValueError, match='verbatim'):
        build_plan(case, tmp_path)
    case['result']['claims']['c1']['status'] = 'incomplete'
    with pytest.raises(ValueError, match='validated'):
        build_plan(case, tmp_path)
    case['result']['model_mode'] = 'mock'
    with pytest.raises(ValueError, match='live'):
        build_plan(case, tmp_path)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('node'), reason='Media tools required')
async def test_real_render_playable_idempotent_and_served_with_ranges(case_id, passage, monkeypatch, client):
    import json

    from app.video import cards
    cards.find_playwright(install=False)
    case = ready_case(case_id, passage)
    def tone(text, output):
        ff(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', str(output)])
    source = settings().media_root / case_id / 'source.mp4'
    source.parent.mkdir(parents=True, exist_ok=True)
    ff(['-f', 'lavfi', '-i', 'color=c=blue:s=720x1280:r=30',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2', '-t', '2',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)])
    update_case(case_id, media_path=str(source))
    speak = Mock(side_effect=tone)
    monkeypatch.setattr('app.video.voice.speech', speak)
    case['result']['video'] = {'options': {'sfx': False, 'brainrot': False}, 'requested': True}
    root = settings().media_root / case_id / 'video'
    plan = render_case(case, root, sfx=False, source_clip=str(source))
    result = json.loads((root / 'result.json').read_text())
    path = root / result['artifact'] / 'response.mp4'
    info = probe(path)
    duration = float(info['format']['duration'])
    assert 44.9 <= duration <= 60.1
    assert any(s['codec_type'] == 'audio' for s in info['streams'])
    assert plan.finding.limitations == ['Abstract only.']
    # The first second contains original 880 Hz audio, not the generated 440 Hz track.
    import array
    import wave
    with wave.open(plan.voice.audio_path) as audio:
        audio.setpos(int(audio.getframerate() * 0.2))
        samples = array.array('h', audio.readframes(int(audio.getframerate() * 0.5)))
    crossings = sum((a < 0) != (b < 0) for a, b in zip(samples, samples[1:]))
    assert abs(crossings - 880) < 10
    from app.video.compose import pixel_rgba
    r, g, b, _ = pixel_rgba(path, 360, 640, seek=0.3)
    assert b > 200 and r < 30 and g < 30
    assert len(pixel_rgba(path, 360, 640, seek=44.5)) == 4
    calls = speak.call_count
    render_case(case, root, sfx=False, source_clip=str(source))
    assert speak.call_count == calls
    from app.video import render_video
    resumed = await render_video(case)
    assert resumed['artifact'] == result['artifact'] and resumed['requested'] is True
    update_case(case_id, result_patch={'video': result})
    response = client.get(f'/api/cases/{case_id}/video', headers={'Range': 'bytes=0-99'})
    assert response.status_code == 206 and len(response.content) == 100
    assert response.headers['content-type'] == 'video/mp4'
    assert client.get(f'/api/cases/{case_id}/video/captions').text.startswith('WEBVTT')
    manifest = client.get(f'/api/cases/{case_id}/video/sources').json()
    assert manifest['references'][0]['quote'] == passage.text
    assert manifest['scenes'][-1]['end'] <= duration + 0.2
    import os
    from pathlib import Path
    export = os.environ.get('HYPECHECK_TEST_ARTIFACT_DIR')
    if export:
        destination = Path(export)
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ('response.mp4', 'manifest.json', 'captions.vtt', 'plan.json'):
            shutil.copyfile(path.parent / filename, destination / filename)
    path.unlink()
    assert client.get(f'/api/cases/{case_id}/video').status_code == 410


def test_legacy_render_path_is_not_served(case_id, client, tmp_path):
    path = tmp_path / 'rebuttal.mp4'
    path.write_bytes(b'private bytes')
    update_case(case_id, result_patch={'render': {'status': 'done', 'path': str(path)}})
    assert client.get(f'/api/cases/{case_id}/video').status_code == 409


def test_retry_resumes_evidence_without_inventing_verdict(case_id, passage, client):
    case = ready_case(case_id, passage)
    item = case['result']['claims']['c1']
    item.pop('verdict')
    item.update(status='incomplete', error='Citation failed')
    update_case(case_id, status='incomplete', result_patch={'claims': {'c1': item}})
    response = client.post(f'/api/cases/{case_id}/retry')
    assert response.status_code == 202
    saved = read_case(case_id)
    assert saved['status'] == 'queued'
    assert saved['result']['claims']['c1']['status'] == 'researched'
    assert 'verdict' not in saved['result']['claims']['c1']
    assert client.post(f'/api/cases/{case_id}/retry').status_code == 409
    assert client.get(f'/api/cases/{case_id}/video').status_code == 409


def test_artifact_path_cannot_escape_case_folder(case_id, passage, client):
    ready_case(case_id, passage)
    update_case(case_id, result_patch={'video': {'status': 'ready', 'artifact': '../../.env'}})
    assert client.get(f'/api/cases/{case_id}/video').status_code == 404


def test_retry_obeys_queue_capacity(case_id, passage, client):
    ready_case(case_id, passage)
    settings().max_active_cases = 0
    assert client.post(f'/api/cases/{case_id}/retry').status_code == 429
    assert read_case(case_id)['status'] == 'complete'
