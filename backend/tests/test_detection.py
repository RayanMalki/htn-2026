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


def reply(ai: float, sentences=None, classification="AI_ONLY", mixed=0.0):
    scored = sentences if sentences is not None else [("One scored sentence.", ai)]
    return {"documents": [{
        "version": "2026-09-13-base", "predicted_class": "ai" if ai > 0.5 else "human",
        "document_classification": classification, "confidence_category": "high",
        "result_message": "Detector message.", "average_generated_prob": ai,
        "class_probabilities": {"human": max(0.0, 1 - ai - mixed), "ai": ai, "mixed": mixed},
        "paragraphs": [{"num_sentences": len(scored), "completely_generated_prob": ai}],
        # The vendor flags almost everything, so the parser must ignore this field.
        "sentences": [{"sentence": t, "generated_prob": p, "highlight_sentence_for_ai": True}
                      for t, p in scored],
    }]}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("GPTZERO_API_KEY", "test-key")
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture
def two_readings(monkeypatch, keyed):
    monkeypatch.setenv("GPTZERO_FILLER_READING", "true")
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


def test_removing_a_one_word_sentence_leaves_clean_punctuation():
    # Real dictated speech, where "Basically." is a whole sentence.
    cleaned, _ = strip_fillers("This is the end of my talk. Basically. That's it.")
    assert cleaned == "This is the end of my talk. That's it."


def test_paragraph_breaks_survive_filler_removal():
    cleaned, _ = strip_fillers("Um, first paragraph here.\n\nBasically, second paragraph here.")
    assert cleaned == "First paragraph here.\n\nSecond paragraph here."


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
async def test_one_reading_by_default_with_filler_counts_kept(keyed):
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=reply(0.93)))
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "scored" and route.call_count == 1
    assert outcome.cleaned is None and outcome.verbatim is not None
    # The local strip still runs, so the counts are reported without a second call.
    assert outcome.fillers_removed > 15 and 0 < outcome.filler_ratio < 1
    assert outcome.note is None


@respx.mock
async def test_document_fields_and_sentence_order_are_parsed(keyed):
    scored = [("Scripted opener.", 0.99), ("My own words here.", 0.18), ("Back to script.", 0.94)]
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200,
        json=reply(0.76, sentences=scored, classification="MIXED", mixed=0.24)))
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    scan = outcome.verbatim
    assert scan.document_classification == "MIXED"
    assert scan.ai_probability == 0.76 and scan.mixed_probability == 0.24
    assert scan.flagged_share == 0.76 and scan.confidence_category == "high"
    # Document order, not ranked, so the transcript can be shaded where the words sit.
    assert [s.text for s in scan.sentences] == [t for t, _ in scored]
    assert [s.generated_prob for s in scan.sentences] == [p for _, p in scored]
    assert scan.paragraphs[0].sentences == 3 and scan.paragraphs[0].generated_prob == 0.76
    assert outcome.script_threshold == 0.5
    assert outcome.prepared_transcript is True
    assert scan.__class__.model_fields.get("sentences") is not None


@respx.mock
async def test_both_readings_when_explicitly_enabled(two_readings):
    route = respx.post(ENDPOINT).mock(side_effect=[
        httpx.Response(200, json=reply(0.04)), httpx.Response(200, json=reply(0.93)),
    ])
    async with httpx.AsyncClient() as client:
        outcome = await Detector(client).scan(analysis(SPOKEN))
    assert outcome.status == "scored" and route.call_count == 2
    assert outcome.verbatim.ai_probability == 0.04 and outcome.cleaned.ai_probability == 0.93
    sent = [json.loads(call.request.content)["document"] for call in route.calls]
    assert sent[0] == " ".join(SPOKEN.split()) and "basically" not in sent[1]
    assert route.calls[0].request.headers["x-api-key"] == "test-key"


@respx.mock
async def test_second_reading_skipped_when_no_fillers_found(two_readings):
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
