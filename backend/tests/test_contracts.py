import pytest
from pydantic import ValidationError

from app.schemas import CaseCreate, Citation, Verdict, validate_verdict


@pytest.mark.parametrize("url", [
    "http://www.instagram.com/reel/x", "https://evil.test/reel/x", "https://127.0.0.1/reel/x",
    "https://www.instagram.com.evil.test/reel/x", "https://user:pw@www.instagram.com/reel/x",
    "https://www.instagram.com:8443/reel/x", "https://www.instagram.com/p/x", "file:///etc/passwd",
    "https://www.instagram.com/reel/../x", "https://www.instagram.com/reel/x%2fy",
])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError):
        CaseCreate(source_url=url)


def test_url_normalizes_tracking():
    assert CaseCreate(source_url="https://instagram.com/reels/Ab_2/?igsh=tracking#fragment").source_url == \
        "https://www.instagram.com/reels/Ab_2/"


@pytest.mark.parametrize("label", ["supports", "contradicts", "uncertain"])
def test_verdict_valid_quotes(passage, label):
    verdict = Verdict(label=label, explanation="Evidence assessment", citations=[
        Citation(passage_id=passage.id, quote=passage.text)], limitations=["Abstract only"])
    assert validate_verdict(verdict, [passage]) == verdict


@pytest.mark.parametrize("citation", [
    {"passage_id": "missing", "quote": "Invented"},
    {"passage_id": "p1", "quote": "Vitamin C cures every cold."},
])
def test_citation_hallucination_rejected(passage, citation):
    with pytest.raises(ValueError):
        validate_verdict(Verdict(label="supports", explanation="Incorrect", citations=[citation], limitations=[]), [passage])


def test_conclusion_requires_evidence():
    with pytest.raises(ValueError):
        validate_verdict(Verdict(label="supports", explanation="Unsupported", citations=[], limitations=[]), [])
    assert validate_verdict(Verdict(label="uncertain", explanation="No evidence found", citations=[], limitations=[]), [])


def test_offsets_are_exact(passage):
    with pytest.raises(ValidationError):
        type(passage).model_validate({**passage.model_dump(), "start": 1})


def test_retracted_passage_not_citable(passage):
    passage.known_retracted = True
    verdict = Verdict(label="supports", explanation="No", citations=[Citation(passage_id=passage.id, quote=passage.text)], limitations=[])
    with pytest.raises(ValueError):
        validate_verdict(verdict, [passage])


@pytest.mark.parametrize("host", ["youtube.com", "www.youtube.com", "m.youtube.com"])
def test_shorts_normalizes_tracking(host):
    assert CaseCreate(source_url=f"https://{host}/shorts/BaW_jenozKc/?si=tracking#fragment").source_url == \
        "https://www.youtube.com/shorts/BaW_jenozKc"


@pytest.mark.parametrize("url", [
    "https://youtube.com.evil.test/shorts/BaW_jenozKc",
    "https://user:pw@youtube.com/shorts/BaW_jenozKc",
    "https://youtube.com:8443/shorts/BaW_jenozKc",
    "https://youtube.com/shorts/../BaW_jenozKc",
    "https://youtube.com/shorts/BaW_jenozKc%2f",
    "https://youtube.com/shorts/invalid",
    "https://youtube.com/watch?v=BaW_jenozKc",
    "https://youtube.com/playlist?list=123",
])
def test_reject_unsupported_youtube_urls(url):
    with pytest.raises(ValueError):
        CaseCreate(source_url=url)


def test_transcript_and_claim_timestamps_allow_full_100_seconds():
    from app.schemas import TranscriptSegment

    assert TranscriptSegment(start=96, end=100, text='Final words').end == 100
    with pytest.raises(ValidationError):
        TranscriptSegment(start=96, end=100.01, text='Too long')
