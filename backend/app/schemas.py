import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreate(StrictModel):
    source_url: str = Field(max_length=2048)

    @field_validator("source_url")
    @classmethod
    def supported_video(cls, value: str) -> str:
        url = urlsplit(value.strip())
        if url.scheme == "https" and not url.username and not url.password and url.port in (None, 443):
            if (url.hostname in {"instagram.com", "www.instagram.com"}
                    and re.fullmatch(r"/reels?/[A-Za-z0-9_-]+/?", url.path)):
                return f"https://www.instagram.com{url.path.rstrip('/')}/"
            if (url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}
                    and re.fullmatch(r"/shorts/[A-Za-z0-9_-]{11}/?", url.path)):
                return f"https://www.youtube.com{url.path.rstrip('/')}"
        raise ValueError("Use a public HTTPS Instagram Reel or YouTube Shorts link.")


class TranscriptSegment(StrictModel):
    start: float = Field(ge=0, le=100)
    end: float = Field(ge=0, le=100)
    text: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Segment end precedes start")
        return self


class Claim(StrictModel):
    id: str = Field(pattern=r"^c[1-3]$")
    text: str = Field(min_length=1, max_length=1000)
    start: float = Field(ge=0, le=100)
    end: float = Field(ge=0, le=100)
    search_terms: list[str] = Field(min_length=1, max_length=3)

    @field_validator("search_terms")
    @classmethod
    def bounded_terms(cls, terms):
        if any(not t.strip() or len(t) > 200 for t in terms):
            raise ValueError("Search terms must be 1–200 characters")
        return terms

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Claim end precedes start")
        return self


class AudioAnalysis(StrictModel):
    transcript: list[TranscriptSegment] = Field(max_length=120)
    claims: list[Claim] = Field(max_length=3)
    omitted_claims: int = Field(ge=0)
    language: str
    usable_speech: bool

    @model_validator(mode="after")
    def unique_claims(self):
        if len({c.id for c in self.claims}) != len(self.claims):
            raise ValueError("Duplicate claim identifiers")
        if self.claims and (not self.usable_speech or not self.transcript):
            raise ValueError("Claims require usable speech and transcript")
        return self


class Passage(StrictModel):
    id: str
    paper_id: str
    title: str
    source_url: str
    provider: Literal["europe_pmc", "medlineplus"] = "europe_pmc"
    external_id: str | None = None
    source_kind: Literal["research_paper", "health_topic", "fact_sheet", "guideline"] = "research_paper"
    published: str | None
    study_types: list[str]
    access_type: Literal["full_text", "abstract_only", "summary"]
    license: str | None = None
    retrieved_at: str | None = None
    updated_at: str | None = None
    section: str
    text: str
    context: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    known_retracted: bool = False

    @model_validator(mode="after")
    def exact_offsets(self):
        if self.context[self.start:self.end] != self.text:
            raise ValueError("Passage offsets must address exact stored source text")
        return self


class Citation(StrictModel):
    passage_id: str
    quote: str = Field(min_length=1, max_length=3000)


class Verdict(StrictModel):
    label: Literal["supports", "contradicts", "uncertain"]
    explanation: str = Field(min_length=1, max_length=2500)
    citations: list[Citation] = Field(max_length=6)
    limitations: list[str] = Field(max_length=10)


class DetectedSentence(StrictModel):
    text: str = Field(max_length=1000)
    generated_prob: float = Field(ge=0, le=1)


class DetectedParagraph(StrictModel):
    index: int = Field(ge=0)
    sentences: int = Field(ge=0)
    generated_prob: float = Field(ge=0, le=1)


class Subclass(StrictModel):
    """How the text was produced within its class. Empty for human-written text.

    ai: pure_ai (straight from a model) or ai_paraphrased (run through a humaniser).
    mixed: concatenated (distinct blocks stitched) or polished (a person wrote it,
    a model smoothed it).
    """

    kind: Literal["ai", "mixed"]
    predicted_class: str = Field(max_length=60)
    confidence_category: str | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)


class Scan(StrictModel):
    basis: Literal["verbatim", "filler_removed"]
    characters: int = Field(ge=0)
    predicted_class: str | None = None
    document_classification: str | None = None
    ai_probability: float | None = Field(default=None, ge=0, le=1)
    human_probability: float | None = Field(default=None, ge=0, le=1)
    mixed_probability: float | None = Field(default=None, ge=0, le=1)
    confidence_category: str | None = None
    summary: str | None = None
    flagged_share: float | None = Field(default=None, ge=0, le=1)
    subclass: Subclass | None = None
    # Every sentence, so the transcript can be shaded in place. The vendor's own
    # highlight flag is not used: it marked 9 of 9 sentences including one at 0.18.
    sentences: list[DetectedSentence] = Field(default_factory=list, max_length=200)
    paragraphs: list[DetectedParagraph] = Field(default_factory=list, max_length=40)


class Detection(StrictModel):
    """Authorship signal for the spoken script. Never an input to a medical verdict."""

    provider: str = "GPTZero"
    status: Literal["scored", "skipped", "unavailable"]
    scanned_at: str
    detector_version: str | None = None
    prepared_transcript: bool = False
    # Sentences at or above this are treated as read from a script. Measured: a
    # creator's ad-lib scored 0.18 and 0.29, the script around it 0.74 to 1.00.
    script_threshold: float = Field(default=0.5, ge=0, le=1)
    fillers_removed: int = Field(default=0, ge=0)
    filler_ratio: float = Field(default=0.0, ge=0, le=1)
    removed_examples: list[str] = Field(default_factory=list, max_length=12)
    verbatim: Scan | None = None
    cleaned: Scan | None = None
    note: str | None = Field(default=None, max_length=500)


def validate_verdict(verdict: Verdict, passages: list[Passage]) -> Verdict:
    evidence = {p.id: p for p in passages if not p.known_retracted}
    if verdict.label != "uncertain" and not verdict.citations:
        raise ValueError("A conclusive verdict requires evidence")
    for citation in verdict.citations:
        if citation.passage_id not in evidence or citation.quote not in evidence[citation.passage_id].text:
            raise ValueError("Citation is not verbatim in retrieved evidence")
    return verdict
