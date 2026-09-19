import json

import httpx
import pytest
import respx
from app.config import settings
from app.detection import ENDPOINT, Detector
from app.schemas import AudioAnalysis
from app.speech import strip_fillers

SPOKEN = (
    "Um, so basically, like, seed oils are, you know, essentially causing chronic inflammation in "
    "your body. I mean, the the research is, like, really clear on this, and uh, honestly, doctors "
    "just will not, like, tell you about it because, you know, of the money involved. So if you "
    "actually want to fix your health, you have got to cut every single seed oil out of your "
    "kitchen today and, um, switch over to butter or tallow instead, because that is kind of what "
    "humans ate for, like, thousands of years before any of this even started."
)
CLEAN = (
    "Routine supplementation with vitamin C did not reduce the incidence of the common cold in the "
    "general population. Across twenty-nine trials the pooled result showed no significant "
    "reduction in incidence for participants taking a daily dose."
)


def analysis(text: str) -> AudioAnalysis:
    return AudioAnalysis.model_validate({
        "transcript": [{"start": 0, "end": 30, "text": text}],
        "claims": [{"id": "c1", "text": "Seed oils cause inflammation", "start": 0, "end": 30,
                    "search_terms": ["seed oil inflammation"]}],
        "omitted_claims": 0, "language": "en", "usable_speech": True,
    })


def reply(ai: float, sentences=("One scored sentence.",)):
    return {"documents": [{
        "version": "2026-09-13-base", "predicted_class": "ai" if ai > 0.5 else "human",
        "confidence_category": "high", "result_message": "Detector message.",
        "class_probabilities": {"human": 1 - ai, "ai": ai, "mixed": 0},
        "sentences": [{"sentence": s, "generated_prob": ai} for s in sentences],
    }]}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("GPTZERO_API_KEY", "test-key")
    settings.cache_clear()
    yield
    settings.cache_clear()


def test_fillers_and_repairs_are_removed():
    cleaned, removed = strip_fillers(SPOKEN)
    assert "seed oils are" in cleaned and "chronic inflammation" in cleaned
    assert "butter or tallow" in cleaned and "thousands of years" in cleaned
    words = {w.strip(",.!?").lower() for w in cleaned.split()}
    assert not words & {"um", "uh", "like", "basically", "essentially", "honestly", "actually"}
    for phrase in ["you know", "i mean", "kind of", "the the"]:
        assert phrase not in cleaned.lower()
    assert len(removed) > 15
    assert cleaned[0].isupper() and "  " not in cleaned and " ," not in cleaned


@pytest.mark.parametrize("text", [
    "I like this study a lot.", "It looks like a meta analysis.", "Something like ten trials agree.",
    "The result was much like the earlier one.",
])
def test_like_is_kept_when_it_carries_meaning(text):
    assert "like" in strip_fillers(text)[0]


def test_like_is_removed_when_it_is_a_filler():
    assert "like" not in strip_fillers("Seed oils are, like, really bad for you.")[0].lower()


def test_noun_phrases_survive():
    assert "kind of" in strip_fillers("What kind of doctor said that?")[0]
    assert "kind of" not in strip_fillers("That result is kind of surprising.")[0]


async def test_skipped_when_no_key_is_configured():
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "skipped" and "GPTZERO_API_KEY" in outcome.note


async def test_skipped_when_transcript_is_too_short(keyed):
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis("Seed oils are bad."))
    assert outcome.status == "skipped" and "characters" in outcome.note


@respx.mock
async def test_both_readings_are_scored(keyed):
    route = respx.post(ENDPOINT).mock(side_effect=[
        httpx.Response(200, json=reply(0.04)), httpx.Response(200, json=reply(0.93)),
    ])
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "scored" and route.call_count == 2
    assert outcome.verbatim.predicted_class == "human" and outcome.verbatim.ai_probability == 0.04
    assert outcome.cleaned.predicted_class == "ai" and outcome.cleaned.ai_probability == 0.93
    assert outcome.fillers_removed > 10 and 0 < outcome.filler_ratio < 1
    assert outcome.prepared_transcript is True
    assert outcome.detector_version == "2026-09-13-base"
    sent = [json.loads(call.request.content)["document"] for call in route.calls]
    assert sent[0] == " ".join(SPOKEN.split()) and sent[1] != sent[0]
    assert "basically" not in sent[1] and route.calls[0].request.headers["x-api-key"] == "test-key"


@respx.mock
async def test_single_call_when_there_are_no_fillers(keyed):
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=reply(0.88)))
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(CLEAN))
    assert route.call_count == 1 and outcome.fillers_removed == 0
    assert outcome.verbatim.ai_probability == outcome.cleaned.ai_probability
    assert "No speech fillers" in outcome.note


@respx.mock
async def test_detector_failure_is_reported_not_raised(keyed):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "unavailable" and outcome.verbatim is None
    assert "No authorship claim is made." in outcome.note
    assert outcome.fillers_removed > 0


@respx.mock
async def test_malformed_response_is_reported_not_raised(keyed):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"documents": []}))
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "unavailable"
