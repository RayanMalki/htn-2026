"""GPTZero authorship detection over the spoken transcript.

The transcript is read once, and the response carries a document class, a
subclass saying how the text was produced (straight from a model, put through a
humaniser, stitched together, or written then polished), and a probability per
sentence used to shade the transcript.

A second reading with speech fillers stripped sits behind GPTZERO_FILLER_READING
and is off: across eight measured samples it never changed a classification.
This is never an input to a medical verdict, and a detector failure never fails
a case.
"""

import asyncio

import httpx
import sentry_sdk

from app.config import settings
from app.db import now
from app.http import request
from app.schemas import (
    AudioAnalysis,
    DetectedParagraph,
    DetectedSentence,
    Detection,
    Scan,
    Subclass,
)
from app.speech import strip_fillers

ENDPOINT = "https://api.gptzero.me/v2/predict/text"
# Below this the detector has too little prose for a meaningful reading.
MINIMUM_CHARACTERS = 200
MAXIMUM_CHARACTERS = 50_000
DEADLINE_SECONDS = 25


def transcript_text(analysis: AudioAnalysis) -> str:
    return " ".join(segment.text.strip() for segment in analysis.transcript if segment.text.strip())


def clamp(value) -> float | None:
    return min(1.0, max(0.0, float(value))) if isinstance(value, (int, float)) else None


def read_subclass(document: dict) -> Subclass | None:
    """Only ai and mixed documents carry one; human text reports an empty object."""
    raw = document.get("subclass") or {}
    for kind in ("ai", "mixed"):
        body = raw.get(kind)
        if isinstance(body, dict) and body.get("predicted_class"):
            return Subclass(
                kind=kind, predicted_class=str(body["predicted_class"])[:60],
                confidence_category=body.get("confidence_category"),
                probabilities={str(k): clamp(v) for k, v in
                               (body.get("class_probabilities") or {}).items()
                               if isinstance(v, (int, float))},
            )
    return None


def read_scan(document: dict, basis: str, characters: int) -> Scan:
    probabilities = document.get("class_probabilities") or {}
    # Document order, not ranked: these shade the transcript where the words sit.
    sentences = [
        DetectedSentence(text=s["sentence"][:1000], generated_prob=clamp(s["generated_prob"]))
        for s in (document.get("sentences") or [])
        if isinstance(s.get("generated_prob"), (int, float)) and s.get("sentence")
    ][:200]
    paragraphs = [
        DetectedParagraph(index=i, sentences=max(0, int(p.get("num_sentences") or 0)),
                          generated_prob=clamp(p["completely_generated_prob"]))
        for i, p in enumerate(document.get("paragraphs") or [])
        if isinstance(p.get("completely_generated_prob"), (int, float))
    ][:40]
    return Scan(
        basis=basis, characters=characters, sentences=sentences, paragraphs=paragraphs,
        predicted_class=document.get("predicted_class"),
        document_classification=document.get("document_classification"),
        ai_probability=clamp(probabilities.get("ai", document.get("completely_generated_prob"))),
        human_probability=clamp(probabilities.get("human")),
        mixed_probability=clamp(probabilities.get("mixed")),
        confidence_category=document.get("confidence_category"),
        summary=document.get("result_message"),
        flagged_share=clamp(document.get("average_generated_prob")),
        subclass=read_subclass(document),
    )


class Detector:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.cfg = settings()

    async def predict(self, text: str) -> dict:
        response = await request(
            self.client, "POST", ENDPOINT,
            headers={"x-api-key": self.cfg.gptzero_api_key, "Content-Type": "application/json"},
            json={"document": text, "multilingual": False},
        )
        body = response.json()
        documents = body.get("documents") or []
        if not documents:
            raise ValueError("GPTZero returned no scored document")
        return documents[0]

    async def scan(self, analysis: AudioAnalysis) -> Detection:
        """Always returns a Detection. Errors are reported in it, never raised."""
        prepared = self.cfg.model_mode == "mock"
        base = Detection(status="skipped", scanned_at=now().isoformat(), prepared_transcript=prepared)
        if not self.cfg.gptzero_api_key:
            return base.model_copy(update={"note": "GPTZERO_API_KEY is not configured."})

        verbatim = transcript_text(analysis)[:MAXIMUM_CHARACTERS]
        if len(verbatim) < MINIMUM_CHARACTERS:
            return base.model_copy(update={
                "note": f"Transcript is {len(verbatim)} characters; "
                        f"at least {MINIMUM_CHARACTERS} are needed for a reading.",
            })

        cleaned, removed = strip_fillers(verbatim)
        spoken_words = max(1, len(verbatim.split()))
        counts = {
            "fillers_removed": len(removed),
            "filler_ratio": round(min(1.0, len(removed) / spoken_words), 4),
            "removed_examples": sorted({w.lower() for w in removed})[:12],
        }
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                first = await self.predict(verbatim)
                # A second reading with speech fillers stripped. Across eight measured
                # samples it never changed a classification, and Deezer (arXiv
                # 2506.18488) report the same for transcript normalisation. It is on
                # anyway: every one of those samples was unambiguous, clearly human or
                # clearly machine, so the borderline case where a second reading could
                # matter was never actually tested. It costs one call on a stage that
                # already runs concurrently with the literature search.
                second = None
                if self.cfg.gptzero_filler_reading:
                    second = first if cleaned == verbatim else (
                        await self.predict(cleaned) if len(cleaned) >= MINIMUM_CHARACTERS else None
                    )
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            return base.model_copy(update={
                **counts, "status": "unavailable",
                "note": "The authorship detector did not respond. No authorship claim is made.",
            })

        note = None
        if self.cfg.gptzero_filler_reading:
            if second is None:
                note = (f"Only {len(cleaned)} characters remained after filler removal, "
                        "so the script-only reading was not taken.")
            elif cleaned == verbatim:
                note = "No speech fillers were found, so both readings are the same text."
        return Detection(
            status="scored", scanned_at=now().isoformat(), prepared_transcript=prepared,
            detector_version=first.get("version"), note=note, **counts,
            verbatim=read_scan(first, "verbatim", len(verbatim)),
            cleaned=read_scan(second, "filler_removed", len(cleaned)) if second is not None else None,
        )
