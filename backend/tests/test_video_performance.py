"""Fast renderer regression checks: real filters, timing and cache invalidation."""
from pathlib import Path

import pytest
from test_video_compose import _plan, _png, _silence, _video_duration, requires_media

from app.video import captions, compose, render
from app.video.plan import Word


def test_ass_quotes_cannot_inject_override_tags(tmp_path):
    plan = _plan()
    from app.video.plan import Voice
    plan.voice = Voice(audio_path='fixture', duration=6, engine='silent',
                       words=[Word(text=r'{\pos(0,0)}', start=1, end=2)])
    content = captions.write_ass(plan, tmp_path / 'captions.ass').read_text()
    assert '｛＼pos(0,0)｝' in content
    assert 'AI-generated voice' in content
    assert '0:00:01.00,0:00:02.00' in content


@requires_media
@pytest.mark.parametrize('split', [False, True])
def test_final_encode_has_captions_audio_and_full_duration(tmp_path, split):
    from app.video.plan import Voice
    plan = _plan()
    plan.brainrot = split
    plan.sfx = True
    plan.voice = Voice(audio_path=_silence(tmp_path / 'voice.wav', 6), duration=6, engine='silent',
                       words=[Word(text='Exact', start=.5, end=1), Word(text='quote.', start=1, end=1.5)])
    for i, scene in enumerate(plan.scenes):
        scene.card_png = _png(tmp_path / f'card{i}.png', 'white')
    compose.compose(plan, tmp_path / 'out', final=True)
    assert abs(_video_duration(plan.output_path) - 6) < .25
    assert compose.probe_size(plan.output_path) == (720, 1280)
    assert (tmp_path / 'out/captions.ass').is_file()
    assert not list((tmp_path / 'out').glob('caption_*.png'))


def test_card_edit_changes_renderer_identity_not_voice_identity(monkeypatch):
    original = Path.read_bytes
    before = render.renderer_identity()
    voice = render.stage_identity('voice')
    def modified(path):
        return original(path) + (b'/* style change */' if path.name == 'cards.mjs' else b'')
    monkeypatch.setattr(Path, 'read_bytes', modified)
    assert render.renderer_identity() != before
    assert render.stage_identity('voice') == voice


def test_two_speech_requests_overlap_but_never_exceed_limit(tmp_path, monkeypatch):
    import threading
    import time

    from app.video import voice
    from app.video.plan import Voice
    plan = _plan()
    active = 0
    peak = 0
    lock = threading.Lock()
    def speech(text, path):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.05)
        path.write_bytes(b'audio')
        with lock:
            active -= 1
    monkeypatch.setattr(voice, 'speech', speech)
    monkeypatch.setattr(voice, 'valid_media', lambda path, **kw: Path(path).exists())
    monkeypatch.setattr(voice, 'probe', lambda path: {'format': {'duration': '2'}})
    monkeypatch.setattr(voice, 'alignment_identity', lambda: [])
    monkeypatch.setattr(voice, 'aligned_words', lambda text, *args: ([Word(text=text, start=0, end=2)], 'estimated'))
    monkeypatch.setattr(voice, 'ff', lambda args, **kw: Path(args[-1]).write_bytes(b'audio'))
    voice.synthesize(plan, tmp_path)
    assert peak == 2
    assert isinstance(plan.voice, Voice)
    assert plan.voice.words[0].end == pytest.approx(2 / voice.PLAYBACK_SPEED)
