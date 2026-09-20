import shutil
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.db import read_case, update_case
from app.schemas import Citation, Claim, Verdict
from app.video import media_info, render_video, storyboard


def ready_case(case_id, passage):
    claim = Claim(id='c1', text='Vitamin C prevents colds.', start=0, end=1, search_terms=['vitamin C'])
    verdict = Verdict(label='contradicts', explanation='The review did not find prevention.',
                      citations=[Citation(passage_id=passage.id, quote=passage.text)], limitations=['Abstract only.'])
    return update_case(case_id, status='complete', result_patch={
        'model_mode': 'live', 'analysis': {'claims': [claim.model_dump()], 'omitted_claims': 1},
        'claims': {'c1': {'status': 'complete', 'claim': claim.model_dump(),
                          'verdict': verdict.model_dump(), 'evidence': [passage.model_dump()]}}})


def test_storyboard_requires_validated_complete_live_verdicts(case_id, passage):
    case = ready_case(case_id, passage)
    scenes, sources = storyboard(case)
    assert sources[0]['quote'] == passage.text
    assert sources[0]['url'] == passage.source_url
    assert any('Abstract only.' == scene['body'] for scene in scenes)
    assert '1 additional claims' in scenes[-1]['narration']
    case['result']['claims']['c1']['verdict']['citations'][0]['quote'] = 'Invented'
    with pytest.raises(ValueError, match='verbatim'):
        storyboard(case)
    case['result']['claims']['c1']['status'] = 'incomplete'
    with pytest.raises(ValueError, match='validated'):
        storyboard(case)
    case['result']['model_mode'] = 'mock'
    with pytest.raises(ValueError, match='live'):
        storyboard(case)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
async def test_real_render_playable_idempotent_and_served_with_ranges(case_id, passage, monkeypatch, client):
    from app.media import run_process

    case = ready_case(case_id, passage)
    async def tone(text, output):
        await run_process('ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                          'sine=frequency=440:duration=0.3', str(output), timeout=10)
    speak = AsyncMock(side_effect=tone)
    monkeypatch.setattr('app.video.speech', speak)
    result = await render_video(case)
    path = settings().media_root / case_id / 'video' / result['artifact'] / 'response.mp4'
    duration, info = await media_info(path)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert video['width'] == 720 and video['height'] == 1280
    assert duration > 1 and any(s['codec_type'] == 'audio' for s in info['streams'])
    calls = speak.call_count
    assert await render_video(case) == result
    assert speak.call_count == calls
    update_case(case_id, result_patch={'video': result})
    response = client.get(f'/api/cases/{case_id}/video', headers={'Range': 'bytes=0-99'})
    assert response.status_code == 206 and len(response.content) == 100
    assert response.headers['content-type'] == 'video/mp4'
    assert client.get(f'/api/cases/{case_id}/video/captions').text.startswith('WEBVTT')
    manifest = client.get(f'/api/cases/{case_id}/video/sources').json()
    assert manifest['references'][0]['quote'] == passage.text
    assert manifest['scenes'][-1]['end'] <= duration + 0.2
    path.unlink()
    assert client.get(f'/api/cases/{case_id}/video').status_code == 410


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
