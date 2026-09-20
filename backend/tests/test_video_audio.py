"""
The audio stages of the rebuttal renderer: script, voice, captions.

Built around the blue-light case from the Saturday research: the creator says blue
light is not ruining your sleep, one supported claim (brightness matters, Wood 2013,
abstract only) and one contradicted claim (wavelength matters for melatonin, West
2011 and Gooley 2010, full text). The plan must give credit first, then correct,
carry an evidence tag on every factual sentence, state the finding as information
with no score, and sit in the 45 to 60 second band. Then the voice stage must work
with no key, no `say` and no whisper, which is what continuous integration has, so
the silent path is exercised on purpose.
"""

import re
import shutil
import wave
from pathlib import Path

import pytest

from app.video.captions import pages
from app.video.script import build_plan
from app.video.voice import synthesize

WEST_CONTEXT = ("Light suppresses melatonin in humans, with the strongest response occurring in the "
                "short-wavelength portion of the spectrum between 446 and 477 nm that appears blue. Blue "
                "monochromatic light has also been shown to be more effective than longer-wavelength light "
                "for enhancing alertness. We measured melatonin in 8 adults exposed to blue LEDs.")
WEST_QUOTE = ("Light suppresses melatonin in humans, with the strongest response occurring in the "
              "short-wavelength portion of the spectrum between 446 and 477 nm that appears blue.")
GOOLEY_CONTEXT = ("Exposure to room light before bedtime suppresses melatonin onset and shortens melatonin "
                  "duration in humans. In 116 healthy volunteers, exposure to room light before bedtime "
                  "suppressed melatonin, resulting in a later melatonin onset in 99% of individuals.")
GOOLEY_QUOTE = "Exposure to room light before bedtime suppresses melatonin onset and shortens melatonin duration in humans."
WOOD_CONTEXT = ("Light level and duration of exposure determine the impact of self-luminous tablets on "
                "melatonin suppression. A 2 hour exposure to a tablet at full brightness suppressed melatonin "
                "by about 22 percent in 13 participants.")
WOOD_QUOTE = "Light level and duration of exposure determine the impact of self-luminous tablets on melatonin suppression."


def passage(pid, paper_id, title, published, types, access, section, text, context):
    return {
        "id": pid, "paper_id": paper_id, "title": title, "source_url": f"https://europepmc.org/article/{paper_id}",
        "provider": "europe_pmc", "external_id": paper_id, "source_kind": "research_paper",
        "published": published, "study_types": types, "access_type": access, "license": None,
        "retrieved_at": None, "updated_at": None, "section": section, "text": text, "context": context,
        "start": context.index(text), "end": context.index(text) + len(text), "known_retracted": False,
    }


def blue_light_case() -> dict:
    west = passage("p1", "PMC1", "Blue light from light-emitting diodes elicits a dose-dependent suppression "
                   "of melatonin in humans", "2011-03-01", ["Randomized Controlled Trial", "Journal Article"],
                   "full_text", "Abstract", WEST_QUOTE, WEST_CONTEXT)
    gooley = passage("p2", "PMC3047226", "Exposure to room light before bedtime suppresses melatonin onset and "
                     "shortens melatonin duration in humans", "2010-12-30", ["Randomized Controlled Trial"],
                     "full_text", "Abstract", GOOLEY_QUOTE, GOOLEY_CONTEXT)
    wood = passage("p3", "MED:22850476", "Light level and duration of exposure determine the impact of "
                   "self-luminous tablets on melatonin suppression", "2013", ["Clinical Trial"],
                   "abstract_only", "Abstract", WOOD_QUOTE, WOOD_CONTEXT)
    return {
        "id": "case-blue-light",
        "source_url": "https://www.instagram.com/reel/abc/",
        "status": "complete",
        "result": {
            "analysis": {"transcript": [
                {"start": 0.0, "end": 4.0, "text": "You mean to tell me the blue light from my phone wasn't ruining my sleep?"},
                {"start": 4.0, "end": 9.0, "text": "The difference was a bright screen versus a dim book."},
                {"start": 9.0, "end": 14.0, "text": "You just need to turn down your brightness."},
            ]},
            "claims": {
                "c1": {
                    "claim": {"id": "c1", "text": "Blue light isn't ruining your sleep", "start": 0.0, "end": 4.0,
                              "search_terms": ["blue light", "melatonin"]},
                    "evidence": [west, gooley], "status": "complete",
                    "verdict": {"label": "contradicts",
                                "explanation": "Blue wavelengths suppress melatonin in humans, dose dependently.",
                                "citations": [{"passage_id": "p1", "quote": WEST_QUOTE},
                                              {"passage_id": "p2", "quote": GOOLEY_QUOTE}],
                                "limitations": []},
                },
                "c2": {
                    "claim": {"id": "c2", "text": "You just need to turn down your brightness", "start": 9.0,
                              "end": 14.0, "search_terms": ["screen brightness", "melatonin"]},
                    "evidence": [wood], "status": "complete",
                    "verdict": {"label": "supports",
                                "explanation": "Light level and duration drive the melatonin effect.",
                                "citations": [{"passage_id": "p3", "quote": WOOD_QUOTE}], "limitations": []},
                },
            },
        },
    }


TAG = re.compile(r"\[E\d+\]")


def test_script_builds_a_stitch_that_credits_then_corrects(tmp_path):
    plan = build_plan(blue_light_case(), tmp_path)
    kinds = [s.kind for s in plan.scenes]
    assert kinds[0] == "clip" and kinds[1] == "claim" and kinds[-2] == "finding" and kinds[-1] == "close"
    papers = [s for s in plan.scenes if s.kind == "paper"]
    assert len(papers) >= 2, "expected a credit paper and at least one correction paper"
    # credit first, correction after
    assert plan.evidence[0].stance == "supports", "the supported claim's paper must come first"
    assert "holds up" in papers[0].narration and "right" in papers[0].narration
    assert "skips" in papers[1].narration
    # the rebuttal targets the contradicted claim
    assert plan.claim == "Blue light isn't ruining your sleep"
    assert plan.finding is not None and plan.finding.label == "mixed"


def test_every_factual_sentence_carries_an_evidence_tag(tmp_path):
    plan = build_plan(blue_light_case(), tmp_path)
    ids = {e.id for e in plan.evidence}
    for scene in plan.scenes:
        if scene.kind != "paper":
            continue
        for sentence in re.split(r"(?<=[.!?])(?<!\.\.)\s+", scene.narration):
            if "found that" in sentence:
                tags = TAG.findall(sentence)
                assert tags, f"factual sentence without a tag: {sentence!r}"
                assert all(t.strip("[]") in ids for t in tags), f"unknown tag in {sentence!r}"
    finding = next(s for s in plan.scenes if s.kind == "finding")
    assert TAG.search(finding.narration), "the finding names the strongest study"
    # the tags are for the page, the card highlight is the verbatim quote
    for scene in plan.scenes:
        if scene.kind == "paper":
            assert scene.card.highlight and scene.card.evidence_id in ids


def test_finding_is_information_never_a_score(tmp_path):
    plan = build_plan(blue_light_case(), tmp_path)
    f = plan.finding
    assert f.label in {"supported", "contradicted", "mixed", "unclear", "insufficient"}
    assert not re.search(r"\b\d+\s*/\s*\d+\b|\bscore\b|\d+\s*out of\s*\d+|[+-]\d\b", f.sentence, re.I)
    assert (f.supports, f.contradicts, f.unclear) == (1, 2, 0)
    assert (f.full_text, f.abstract_only) == (2, 1)
    finding_scene = next(s for s in plan.scenes if s.kind == "finding")
    assert "studies contradict" in finding_scene.narration and "backs" in finding_scene.narration


def test_estimated_duration_sits_in_the_band(tmp_path):
    plan = build_plan(blue_light_case(), tmp_path)
    assert 45.0 <= plan.duration <= 60.0, plan.duration
    starts = [s.start for s in plan.scenes]
    assert starts == sorted(starts) and starts[0] == 0.0
    assert all(b.end > b.start for b in plan.scenes)
    assert (tmp_path / "plan.json").exists()


def test_silent_voice_path_works_with_nothing_installed(tmp_path, monkeypatch):
    for key in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    plan = build_plan(blue_light_case(), tmp_path)
    before = [(s.start, s.end) for s in plan.scenes]
    plan = synthesize(plan, tmp_path, engine_order=["silent"])
    v = plan.voice
    assert v is not None and v.engine == "silent" and v.timings_from == "estimated"
    assert Path(v.audio_path).exists()
    with wave.open(v.audio_path, "rb") as handle:
        assert handle.getnchannels() == 1 and handle.getframerate() == 48000
    assert v.duration > 0 and abs(v.duration - plan.scenes[-1].end) < 0.01
    # scenes were moved onto the real audio: still ordered, contiguous, ending at the duration
    assert plan.scenes[0].start == 0.0
    for a, b in zip(plan.scenes, plan.scenes[1:], strict=False):
        assert abs(a.end - b.start) < 0.01 and b.end > b.start
    assert [(s.start, s.end) for s in plan.scenes] != before or v.duration == before[-1][1]
    # every spoken word got a timing and the tags were not spoken
    assert v.words and all(w.end >= w.start for w in v.words)
    assert not any("[E" in w.text for w in v.words)


def test_caption_pages_are_short_ordered_and_keep_units_together(tmp_path, monkeypatch):
    for key in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    plan = synthesize(build_plan(blue_light_case(), tmp_path), tmp_path, engine_order=["silent"])
    caps = pages(plan)
    assert caps, "no caption pages"
    for page in caps:
        n = len(page["text"].split())
        assert 1 <= n <= 4, page
        assert 0 <= page["start"] <= page["end"] <= plan.voice.duration + 0.01, page
    starts = [p["start"] for p in caps]
    assert starts == sorted(starts)
    assert abs(caps[0]["start"] - plan.voice.words[0].start) < 0.01
    assert abs(caps[-1]["end"] - plan.voice.words[-1].end) < 0.01
    # "446 and 477 nm" from the West quote must never be split across pages
    joined = [p["text"] for p in caps]
    for i, text in enumerate(joined):
        last = text.split()[-1].strip(".,;:")
        if re.fullmatch(r"\d[\d,.]*", last) and i + 1 < len(joined):
            first_next = joined[i + 1].split()[0].strip(".,;:").lower()
            assert first_next not in {"nm", "nanometres", "to", "and", "percent", "adults"}, (text, joined[i + 1])
    assert any("446 and 477 nm" in p["text"] for p in caps), joined


def test_network_voice_is_cached_by_engine_and_narration(tmp_path, monkeypatch):
    """ElevenLabs' free tier is about a dozen renders a month. The same script must
    never spend a second call, and switching engines must never serve the wrong file."""
    from app.video import voice as voice_module

    calls = []

    def fake_elevenlabs(text, out_dir):
        calls.append(text)
        wav = Path(out_dir) / "voice.wav"
        voice_module._write_silence(wav, 3.0)
        return wav, [voice_module.Word(text="fake", start=0.0, end=3.0)]

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("HYPECHECK_VOICE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setitem(voice_module.ENGINES, "elevenlabs", fake_elevenlabs)

    first = synthesize(build_plan(blue_light_case(), tmp_path / "a"), tmp_path / "a", engine_order=["elevenlabs"])
    second = synthesize(build_plan(blue_light_case(), tmp_path / "b"), tmp_path / "b", engine_order=["elevenlabs"])
    assert len(calls) == 1, "the second render should have come from the cache"
    assert first.voice.engine == second.voice.engine == "elevenlabs"
    assert Path(second.voice.audio_path).exists() and second.voice.timings_from == first.voice.timings_from
    # a different engine name must miss, even for the identical narration
    key_a = voice_module._cache_key("elevenlabs", "same text")
    key_b = voice_module._cache_key("openai", "same text")
    assert key_a != key_b


@pytest.mark.skipif(not shutil.which("say") or not shutil.which("ffmpeg"), reason="macOS say not available")
def test_macos_say_engine_produces_real_audio(tmp_path, monkeypatch):
    for key in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    plan = synthesize(build_plan(blue_light_case(), tmp_path), tmp_path, engine_order=["macos_say", "silent"])
    assert plan.voice.engine == "macos_say"
    assert 30.0 < plan.voice.duration < 90.0, plan.voice.duration
    assert plan.voice.timings_from in {"whisper", "estimated"}
    assert plan.voice.words
