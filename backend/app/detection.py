"""GPTZero authorship detection over the spoken transcript.

Two readings are taken. The verbatim transcript is what was actually said. The
filler-removed transcript approximates the script behind the delivery, because
speech disfluencies read as human to a detector regardless of who wrote the words.
Both are reported; neither is an input to a medical verdict, and a detection
failure never fails a case.
"""

import asyncio

import httpx
import sentry_sdk

from app.config import settings
from app.db import now
from app.http import request
from app.schemas import AudioAnalysis, DetectedSentence, Detection, Scan
from app.speech import strip_fillers

ENDPOINT = "https://api.gptzero.me/v2/predict/text"
# Below this the detector has too little prose for a meaningful reading.
MINIMUM_CHARACTERS = 200
MAXIMUM_CHARACTERS = 50_000
DEADLINE_SECONDS = 25


def transcript_text(analysis: AudioAnalysis) -> str:
    return " ".join(segment.text.strip() for segment in analysis.transcript if segment.text.strip())


def read_scan(document: dict, basis: str, characters: int) -> Scan:
    probabilities = document.get("class_probabilities") or {}
    scored = [
        s for s in document.get("sentences") or []
        if isinstance(s.get("generated_prob"), (int, float)) and s.get("sentence")
    ]
    top = sorted(scored, key=lambda s: s["generated_prob"], reverse=True)[:3]
    ai = probabilities.get("ai", document.get("completely_generated_prob"))
    return Scan(
        basis=basis, characters=characters,
        predicted_class=document.get("predicted_class"),
        ai_probability=min(1.0, max(0.0, float(ai))) if isinstance(ai, (int, float)) else None,
        confidence_category=document.get("confidence_category"),
        summary=document.get("result_message"),
        top_sentences=[DetectedSentence(text=s["sentence"][:1000],
                                        generated_prob=min(1.0, max(0.0, float(s["generated_prob"]))))
                       for s in top],
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
                # A second call is only worth making when stripping actually changed the text.
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
