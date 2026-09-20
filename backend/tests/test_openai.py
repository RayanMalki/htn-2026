import json

import pytest
import respx

from app.config import settings
from app.models import models
from app.openai_models import BASE, ClaimExtraction, OpenAIModels
from app.schemas import Claim


def response(output):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(output)}]}]}


def configure():
    settings().openai_api_key = 'test-key'
    settings().model_provider = 'openai'


def test_direct_provider_selection():
    configure()
    settings().model_mode = 'live'
    assert type(models()) is OpenAIModels
    assert settings().model_configured
    settings().openai_api_key = ''
    assert not settings().model_configured


@respx.mock
async def test_transcription_and_claim_timestamps(tmp_path):
    configure()
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'audio fixture')
    stt = respx.post(BASE + '/audio/transcriptions').respond(200, json={
        'text': 'Walking improves sleep.', 'language': 'english',
        'segments': [{'start': 0.4, 'end': 2.7, 'text': 'Walking improves sleep.'}],
    })
    llm = respx.post(BASE + '/responses').respond(200, json=response({
        'claims': [{'text': 'Walking improves sleep.', 'first_segment': 0, 'last_segment': 0,
                    'search_terms': ['walking sleep quality'], 'details': {'intervention': 'Walking',
                        'outcome': 'sleep', 'population': None}}], 'omitted_claims': 0,
    }))
    result = await OpenAIModels().analyze(audio, duration=3)
    assert result.claims[0].start == 0.4 and result.claims[0].end == 2.7
    assert result.transcript[0].text == 'Walking improves sleep.'
    assert result.claims[0].details.intervention == 'Walking'
    assert result.claims[0].details.population is None
    assert b'verbose_json' in stt.calls[0].request.content
    assert b'timestamp_granularities[]' in stt.calls[0].request.content
    body = json.loads(llm.calls[0].request.content)
    assert body['store'] is False and body['text']['format']['strict'] is True
    assert body['text']['format']['schema']['additionalProperties'] is False
    assert llm.calls[0].request.headers['Authorization'] == 'Bearer test-key'


@respx.mock
@pytest.mark.parametrize('body', [
    {'status': 'incomplete', 'output': []},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
    {'status': 'completed', 'output': []},
])
async def test_incomplete_or_refused_model_output_fails(body):
    configure()
    respx.post(BASE + '/responses').respond(200, json=body)
    with pytest.raises(ValueError):
        await OpenAIModels().generate('extract', ClaimExtraction)


@respx.mock
async def test_text_judgment_uses_responses_endpoint(passage):
    configure()
    route = respx.post(BASE + '/responses').respond(200, json=response({
        'label': 'contradicts', 'explanation': 'The review did not find prevention.', 'limitations': [],
        'quote_ids': ['q1'],
        'paper_assessments': [{'paper_id': passage.paper_id, 'applicability': 'direct',
            'finding': 'contradicts', 'explanation': 'Prevention was studied.',
            'quote_ids': ['q1'], 'limitations': ['Abstract only.'], 'possible_overlap_with': []}],
    }))
    result = await OpenAIModels().judge(
        Claim(id='c1', text='Vitamin C prevents colds', start=0, end=1, search_terms=['vitamin C cold']),
        [passage],
    )
    assert result.label == 'contradicts'
    assert result.citations[0].quote == passage.text
    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content)['text']['format']['name'] == 'SelectedVerdict'
    schema = json.loads(route.calls[0].request.content)['text']['format']['schema']
    assert schema['properties']['paper_assessments']['minItems'] == 1
    assert schema['properties']['paper_assessments']['maxItems'] == 1
    assert schema['$defs']['SelectedPaper']['properties']['paper_id']['const'] == passage.paper_id


@respx.mock
async def test_invalid_citations_are_rejected(passage):
    configure()
    respx.post(BASE + '/responses').respond(200, json=response({
        'label': 'supports', 'explanation': 'Incorrect quote', 'limitations': [],
        'quote_ids': ['invented'],
    }))
    with pytest.raises(ValueError, match='Input should be'):
        await OpenAIModels().judge(Claim(id='c1', text='claim', start=0, end=1, search_terms=['topic']), [passage])


@respx.mock
@pytest.mark.parametrize('body', [
    {'text': 'Speech', 'language': 'english', 'segments': []},
    {'text': 'Speech', 'language': 'english', 'segments': [{'text': 'Speech', 'start': 0, 'end': 20}]},
    {'text': 'Speech', 'segments': [{'text': 'Speech', 'start': 0, 'end': 1}]},
])
async def test_bad_transcription_does_not_invent_timing(tmp_path, body):
    configure()
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'fixture')
    respx.post(BASE + '/audio/transcriptions').respond(200, json=body)
    with pytest.raises(ValueError):
        await OpenAIModels().analyze(audio, duration=2)


@respx.mock
async def test_unknown_segment_is_rejected(tmp_path):
    configure()
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'fixture')
    respx.post(BASE + '/audio/transcriptions').respond(200, json={
        'text': 'Speech', 'language': 'english', 'segments': [{'text': 'Speech', 'start': 0, 'end': 1}],
    })
    respx.post(BASE + '/responses').respond(200, json=response({
        'claims': [{'text': 'claim', 'first_segment': 0, 'last_segment': 4, 'search_terms': ['topic']}],
        'omitted_claims': 0,
    }))
    with pytest.raises(ValueError, match='unknown transcript segment'):
        await OpenAIModels().analyze(audio, duration=2)
