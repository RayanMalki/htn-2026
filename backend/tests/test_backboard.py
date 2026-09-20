import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.backboard import BASE, BackboardModels, ExtractedClaims
from app.config import settings
from app.models import GeminiModels, MockModels, models
from app.schemas import Claim


def configure():
    settings().model_mode = 'live'
    settings().model_provider = 'backboard'
    settings().backboard_api_key = 'test-backboard-key'


def test_provider_selection_and_readiness():
    assert isinstance(models(), MockModels)
    settings().model_mode = 'live'
    settings().model_provider = 'backboard'
    settings().backboard_api_key = ''
    settings().gemini_api_key = 'google-key-does-not-enable-backboard'
    assert not settings().model_configured
    configure()
    assert isinstance(models(), BackboardModels)
    assert settings().model_configured
    assert settings().model_id.startswith('backboard/')
    settings().model_provider = 'gemini'
    assert type(models()) is GeminiModels


@respx.mock
async def test_text_wire_contract_and_validated_judgment(passage):
    configure()
    output = {'label': 'contradicts', 'explanation': 'The supplied review did not find prevention.',
              'quote_ids': ['q1'], 'limitations': ['Limited search.']}
    route = respx.post(BASE + '/threads/messages').respond(200, json={'status': 'COMPLETED', 'content': json.dumps(output)})
    claim = Claim(id='c1', text='Vitamin C prevents colds', start=0, end=10, search_terms=['vitamin C cold'])
    result = await BackboardModels().judge(claim, [passage])
    assert result.label == 'contradicts'
    sent = json.loads(route.calls[0].request.content)
    assert sent['memory'] == sent['web_search'] == 'off'
    assert sent['tools'] == [] and sent['json_output'] is True
    assert sent['llm_provider'] == 'openai'
    assert 'thread_id' not in sent and 'assistant_id' not in sent
    assert route.calls[0].request.headers['X-API-Key'] == 'test-backboard-key'
    assert 'key' not in str(route.calls[0].request.url)


@respx.mock
async def test_invalid_citations_are_rejected(passage):
    configure()
    route = respx.post(BASE + '/threads/messages').respond(200, json={
        'status': 'COMPLETED', 'content': json.dumps({
            'label': 'supports', 'explanation': 'Incorrect quote', 'limitations': [],
            'quote_ids': ['invented'],
        }),
    })
    claim = Claim(id='c1', text='claim', start=0, end=1, search_terms=['topic'])
    with pytest.raises(ValueError, match='Input should be'):
        await BackboardModels().judge(claim, [passage])
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize('response', [
    {'status': 'FAILED', 'content': '{}'},
    {'status': 'REQUIRES_ACTION', 'content': '{}'},
    {'status': 'COMPLETED', 'content': 'not json'},
    {'status': 'COMPLETED', 'content': '{}', 'retrieved_files': [{'id': 'external'}]},
])
async def test_invalid_or_unisolated_responses_fail(response):
    configure()
    respx.post(BASE + '/threads/messages').respond(200, json=response)
    with pytest.raises(ValueError):
        await BackboardModels().generate('extract', ExtractedClaims)


@respx.mock
async def test_audio_wire_contract_and_retry(tmp_path):
    configure()
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'fixture-mp3-bytes')
    route = respx.post(BASE + '/threads/messages').mock(side_effect=[
        httpx.Response(503), httpx.Response(200, json={'voice_records': {'stt': {'transcript': 'spoken words'}}}),
    ])
    async with httpx.AsyncClient() as client:
        assert await BackboardModels().transcribe(client, audio) == 'spoken words'
    assert route.call_count == 2
    for call in route.calls:
        wire = call.request.content
        assert b'name="audio_file"' in wire and b'fixture-mp3-bytes' in wire
        assert b'"model": "whisper-1"' in wire
        assert b'name="send_to_llm"\r\n\r\nfalse' in wire


@respx.mock
async def test_missing_transcript_is_failure_not_silence(tmp_path):
    configure()
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'audio')
    respx.post(BASE + '/threads/messages').respond(200, json={'content': 'invented fallback'})
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match='transcript'):
            await BackboardModels().transcribe(client, audio)


async def test_window_timestamps_come_from_audio_boundaries(tmp_path, monkeypatch):
    configure()
    import app.backboard as module
    monkeypatch.setattr(module, 'run_process', AsyncMock())
    adapter = BackboardModels()
    adapter.transcribe = AsyncMock(return_value='A medical claim spoken here.')
    adapter.generate = AsyncMock(return_value=ExtractedClaims.model_validate({
        'claims': [{'text': 'A medical claim', 'first_window': 1, 'last_window': 2, 'search_terms': ['medical topic']}],
        'omitted_claims': 0, 'language': 'en',
    }))
    result = await adapter.analyze(tmp_path / 'audio.mp3', duration=24.5)
    assert [(s.start, s.end) for s in result.transcript] == [(0, 10), (10, 20), (20, 24.5)]
    assert (result.claims[0].start, result.claims[0].end) == (10, 24.5)
    assert not list(tmp_path.glob('stt-*'))
    adapter.generate.return_value.claims[0].last_window = 100
    with pytest.raises(ValueError, match='unknown transcript window'):
        await adapter.analyze(tmp_path / 'audio.mp3', duration=24.5)


async def test_silence_has_no_claims(tmp_path, monkeypatch):
    configure()
    import app.backboard as module
    monkeypatch.setattr(module, 'run_process', AsyncMock())
    adapter = BackboardModels()
    adapter.transcribe = AsyncMock(return_value='')
    adapter.generate = AsyncMock()
    result = await adapter.analyze(tmp_path / 'audio.mp3', duration=1)
    assert not result.usable_speech and not result.claims
    adapter.generate.assert_not_called()


@respx.mock
async def test_restricted_balance_is_not_model_access(tmp_path):
    from app.backboard import BackboardCreditError
    configure()
    respx.post(BASE + '/threads/messages').respond(200, json={
        'status': 'FAILED', 'content': 'Your free credit is reserved for Memory & RAG and cannot cover chat.',
    })
    with pytest.raises(BackboardCreditError):
        await BackboardModels().generate('access check', ExtractedClaims)
    respx.post(BASE + '/threads/messages').respond(400, json={
        'detail': 'Your free credit is reserved for Memory & RAG and cannot cover voice transcription.',
    })
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'audio')
    async with httpx.AsyncClient() as client:
        with pytest.raises(BackboardCreditError):
            await BackboardModels().transcribe(client, audio)
