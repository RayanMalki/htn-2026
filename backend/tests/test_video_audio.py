"""Evidence integrity and narration contracts; fixtures do not assert medical truth."""
import copy
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.video.captions import pages
from app.video.plan import Word
from app.video.script import ScriptBudgetError, build_plan
from app.video.voice import NarrationError, _cache_key, aligned_words, speech, synthesize

EXAMPLE = Path(__file__).resolve().parents[1] / 'app/video/examples/blue_light_case.json'


def blue_light_case():
    return json.loads(EXAMPLE.read_text())


def test_one_claim_does_not_merge_conflicting_claim_verdicts(tmp_path):
    case = blue_light_case()
    case['result']['claims']['c1']['verdict']['limitations'] = ['The search is limited.']
    plan = build_plan(case, tmp_path)
    assert plan.selected_claim_id == 'c1'
    assert plan.finding.label == 'contradicts'
    assert plan.finding.limitations == ['The search is limited.']
    assert all(e.claim_id == 'c1' for e in plan.evidence)
    assert not any('nobody knows' in s.narration for s in plan.scenes)
    assert any(s.narration == 'The search is limited.' for s in plan.scenes)
    for s in plan.scenes:
        if s.kind == 'paper':
            ev = next(e for e in plan.evidence if e.id == s.card.evidence_id)
            assert s.card.highlight in ev.quote
            assert 'SOURCE EXCERPT' in s.card.eyebrow


@pytest.mark.parametrize('label', ['supports', 'contradicts', 'uncertain'])
def test_saved_verdict_preserved(tmp_path, label):
    case = blue_light_case()
    for item in case['result']['claims'].values():
        item['verdict']['label'] = label
    plan = build_plan(case, tmp_path)
    assert plan.finding.label == label


def test_citations_are_not_study_counts_and_summaries_are_not_abstracts(tmp_path):
    case = blue_light_case()
    item = case['result']['claims']['c1']
    item['verdict']['citations'].append(copy.deepcopy(item['verdict']['citations'][0]))
    item['evidence'][1].update(provider='medlineplus', source_kind='health_topic', access_type='summary')
    plan = build_plan(case, tmp_path)
    assert plan.finding.papers == 1 and plan.finding.summaries == 1
    assert plan.evidence[1].access == 'summary'
    assert not any('stance' in e.model_dump() for e in plan.evidence)


def test_uncited_uncertainty_and_retracted_citations(tmp_path):
    case = blue_light_case()
    item = case['result']['claims']['c1']
    item['evidence'][0]['known_retracted'] = True
    with pytest.raises(ValueError, match='verbatim'):
        build_plan(case, tmp_path)
    item['verdict'].update(label='uncertain', citations=[])
    plan = build_plan(case, tmp_path)
    assert plan.finding.label == 'uncertain' and not plan.evidence


def test_over_budget_preserves_essential_words_by_failing(tmp_path):
    case = blue_light_case()
    case['result']['claims']['c1']['verdict']['limitations'] = ['Important qualification. ' * 100]
    with pytest.raises(ScriptBudgetError, match='budget'):
        build_plan(case, tmp_path)


def test_original_excerpt_uses_selected_claim_timestamps(tmp_path):
    case = blue_light_case()
    case['result']['analysis']['claims'][0].update(start=12, end=17)
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'fixture')
    plan = build_plan(case, tmp_path / 'render', source_clip=str(source))
    assert plan.source_start == 12 and plan.source_duration == 5
    assert plan.scenes[0].kind == 'clip' and plan.scenes[0].narration == ''
    source.unlink()
    assert build_plan(case, tmp_path / 'missing', source_clip=str(source)).scenes[0].kind == 'claim'


def test_voice_failure_never_succeeds_silently(tmp_path, monkeypatch):
    settings().openai_api_key = 'test-key'
    request = httpx.Request('POST', 'https://api.openai.com/v1/audio/speech')
    response = httpx.Response(429, request=request)
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: response)
    with pytest.raises(NarrationError, match='credits'):
        speech('Hello.', tmp_path / 'voice.wav')
    assert not (tmp_path / 'voice.wav').exists()


def test_voice_settings_invalidate_cache():
    key = _cache_key('openai', 'Text')
    settings().tts_voice = 'other'
    assert key != _cache_key('openai', 'Text')
    key = _cache_key('openai', 'Text')
    settings().tts_model = 'other'
    assert key != _cache_key('openai', 'Text')


def test_bad_alignment_is_labeled_estimated(monkeypatch, tmp_path):
    monkeypatch.setattr('app.video.voice._whisper_words', lambda *a: [Word(text='Wrong', start=0, end=9)])
    words, mode = aligned_words('Correct words.', tmp_path / 'audio', tmp_path, 1)
    assert mode == 'estimated' and words[-1].end <= 1.001


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='Media tools required')
def test_voice_audio_cached_before_alignment_failure_and_caption_pages(tmp_path, monkeypatch):
    from app.video.runtime import ff
    calls = []
    def fake(text, output):
        calls.append(text)
        ff(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', str(output)])
    monkeypatch.setattr('app.video.voice.speech', fake)
    case = blue_light_case()
    plan = synthesize(build_plan(case, tmp_path / 'a'), tmp_path / 'a')
    count = len(calls)
    second = synthesize(build_plan(case, tmp_path / 'b'), tmp_path / 'b')
    assert len(calls) == count
    assert plan.duration == second.duration == 45
    caps = pages(plan)
    assert caps and all(0 <= p['start'] < p['end'] <= 45 for p in caps)
