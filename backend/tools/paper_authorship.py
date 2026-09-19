"""
AI-authorship scanning for the papers HypeCheck cites, not just the creator's script.

The team's gptzero-authorship branch (backend/app/detection.py) already scores a
TikTok transcript for machine-written prose: one call to GPTZero's predict/text
endpoint, parsed into a Scan with per-sentence and per-paragraph probabilities plus
a subclass (pure AI, paraphrased, stitched, polished). This reuses that exact
request and parsing shape, pointed at the FULL TEXT of a cited paper instead of a
transcript, and stores every result in a small local database so the number grows
with every paper the fact-checker ever cites, per the team's decision.

Deliberately scoped to full text only, not abstracts: an abstract is short, terse,
and stylistically unlike the rest of the paper, so a detector reading only 150 to
250 words of dense summary is unreliable in a different way than it is on prose.
Papers below the resolver's own full-text threshold are skipped, not scored badly.

Standalone here because push access to the team repo was pull-only as of the last
check. The shape mirrors backend/app/schemas.py's Scan and Subclass models closely
enough that porting this into detection.py is mostly renaming, not rewriting.

Usage:
    export GPTZERO_API_KEY=...
    python3 paper_authorship.py scan <pmcid_or_doi> <path_to_fulltext.txt>
    python3 paper_authorship.py report          # print everything in the database
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ENDPOINT = "https://api.gptzero.me/v2/predict/text"
MINIMUM_CHARACTERS = 200
MAXIMUM_CHARACTERS = 50_000
DB_PATH = Path(__file__).with_name("paper_authorship.db")


def clamp(value) -> float | None:
    return min(1.0, max(0.0, float(value))) if isinstance(value, (int, float)) else None


@dataclass
class Sentence:
    text: str
    generated_prob: float | None


@dataclass
class Paragraph:
    index: int
    sentences: int
    generated_prob: float | None


@dataclass
class Subclass:
    kind: str  # "ai" or "mixed"
    predicted_class: str
    confidence_category: str | None
    probabilities: dict = field(default_factory=dict)


@dataclass
class PaperScan:
    """One paper's authorship reading. Mirrors backend/app/schemas.py's Scan."""

    paper_id: str  # pmcid or doi, whichever identifies the paper elsewhere in the pipeline
    status: str  # "scored" | "skipped" | "unavailable"
    scanned_at: str
    characters: int
    predicted_class: str | None = None
    document_classification: str | None = None
    ai_probability: float | None = None
    human_probability: float | None = None
    mixed_probability: float | None = None
    confidence_category: str | None = None
    summary: str | None = None
    flagged_share: float | None = None
    subclass: Subclass | None = None
    sentences: list[Sentence] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    note: str | None = None


def read_subclass(document: dict) -> Subclass | None:
    """Only ai and mixed documents carry one, same rule as detection.py."""
    raw = document.get("subclass") or {}
    for kind in ("ai", "mixed"):
        body = raw.get(kind)
        if isinstance(body, dict) and body.get("predicted_class"):
            return Subclass(
                kind=kind,
                predicted_class=str(body["predicted_class"])[:60],
                confidence_category=body.get("confidence_category"),
                probabilities={
                    str(k): clamp(v) for k, v in (body.get("class_probabilities") or {}).items()
                    if isinstance(v, (int, float))
                },
            )
    return None


def read_scan(paper_id: str, document: dict, characters: int) -> PaperScan:
    probabilities = document.get("class_probabilities") or {}
    sentences = [
        Sentence(text=s["sentence"][:1000], generated_prob=clamp(s["generated_prob"]))
        for s in (document.get("sentences") or [])
        if isinstance(s.get("generated_prob"), (int, float)) and s.get("sentence")
    ][:200]
    paragraphs = [
        Paragraph(index=i, sentences=max(0, int(p.get("num_sentences") or 0)),
                  generated_prob=clamp(p["completely_generated_prob"]))
        for i, p in enumerate(document.get("paragraphs") or [])
        if isinstance(p.get("completely_generated_prob"), (int, float))
    ][:40]
    return PaperScan(
        paper_id=paper_id, status="scored", scanned_at=datetime.now(UTC).isoformat(),
        characters=characters,
        predicted_class=document.get("predicted_class"),
        document_classification=document.get("document_classification"),
        ai_probability=clamp(probabilities.get("ai", document.get("completely_generated_prob"))),
        human_probability=clamp(probabilities.get("human")),
        mixed_probability=clamp(probabilities.get("mixed")),
        confidence_category=document.get("confidence_category"),
        summary=document.get("result_message"),
        flagged_share=clamp(document.get("average_generated_prob")),
        subclass=read_subclass(document),
        sentences=sentences,
        paragraphs=paragraphs,
    )


def _predict(text: str, api_key: str, timeout: float = 25.0) -> dict:
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"document": text, "multilingual": False}).encode(),
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    documents = body.get("documents") or []
    if not documents:
        raise ValueError("GPTZero returned no scored document")
    return documents[0]


def scan_paper(paper_id: str, full_text: str, api_key: str | None) -> PaperScan:
    """Always returns a PaperScan. Errors are reported in it, never raised, same
    contract as the team's Detector.scan for the transcript path."""
    now = datetime.now(UTC).isoformat()
    if not api_key:
        return PaperScan(paper_id=paper_id, status="skipped", scanned_at=now, characters=0,
                          note="GPTZERO_API_KEY is not configured.")
    text = full_text[:MAXIMUM_CHARACTERS]
    if len(text) < MINIMUM_CHARACTERS:
        return PaperScan(paper_id=paper_id, status="skipped", scanned_at=now, characters=len(text),
                          note=f"Only {len(text)} characters of full text; at least {MINIMUM_CHARACTERS} needed.")
    try:
        document = _predict(text, api_key)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return PaperScan(paper_id=paper_id, status="unavailable", scanned_at=now, characters=len(text),
                          note=f"The authorship detector did not respond: {str(exc)[:100]}")
    return read_scan(paper_id, document, len(text))


# --- the database: every paper ever cited, growing with use ---------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_authorship (
            paper_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            characters INTEGER NOT NULL,
            ai_probability REAL,
            human_probability REAL,
            mixed_probability REAL,
            document_classification TEXT,
            subclass_kind TEXT,
            subclass_predicted_class TEXT,
            note TEXT,
            raw_json TEXT NOT NULL
        )
    """)
    return conn


def store(scan: PaperScan) -> None:
    """Insert or refresh one paper's reading. Called every time the resolver gets
    full text for a paper, so the table is a byproduct of normal citation, not a
    separate crawl, per the team's decision to grow it from real use."""
    raw = json.dumps({
        "paper_id": scan.paper_id, "status": scan.status, "scanned_at": scan.scanned_at,
        "characters": scan.characters, "predicted_class": scan.predicted_class,
        "document_classification": scan.document_classification,
        "ai_probability": scan.ai_probability, "human_probability": scan.human_probability,
        "mixed_probability": scan.mixed_probability, "confidence_category": scan.confidence_category,
        "summary": scan.summary, "flagged_share": scan.flagged_share,
        "subclass": (scan.subclass.__dict__ if scan.subclass else None),
        "sentences": [s.__dict__ for s in scan.sentences],
        "paragraphs": [p.__dict__ for p in scan.paragraphs],
        "note": scan.note,
    })
    with _db() as conn:
        conn.execute("""
            INSERT INTO paper_authorship
                (paper_id, status, scanned_at, characters, ai_probability, human_probability,
                 mixed_probability, document_classification, subclass_kind,
                 subclass_predicted_class, note, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                status=excluded.status, scanned_at=excluded.scanned_at,
                characters=excluded.characters, ai_probability=excluded.ai_probability,
                human_probability=excluded.human_probability, mixed_probability=excluded.mixed_probability,
                document_classification=excluded.document_classification,
                subclass_kind=excluded.subclass_kind, subclass_predicted_class=excluded.subclass_predicted_class,
                note=excluded.note, raw_json=excluded.raw_json
        """, (
            scan.paper_id, scan.status, scan.scanned_at, scan.characters,
            scan.ai_probability, scan.human_probability, scan.mixed_probability,
            scan.document_classification, (scan.subclass.kind if scan.subclass else None),
            (scan.subclass.predicted_class if scan.subclass else None), scan.note, raw,
        ))


def report() -> None:
    with _db() as conn:
        rows = conn.execute("""
            SELECT paper_id, status, characters, ai_probability, document_classification,
                   subclass_kind, subclass_predicted_class
            FROM paper_authorship ORDER BY scanned_at DESC
        """).fetchall()
    if not rows:
        print("no papers scanned yet")
        return
    scored = [r for r in rows if r[1] == "scored"]
    print(f"{'PAPER':16}{'STATUS':11}{'CHARS':>8}  {'AI PROB':>8}  {'CLASS':12}  SUBCLASS")
    print("-" * 78)
    for paper_id, status, chars, ai_prob, doc_class, sub_kind, sub_class in rows:
        prob = f"{ai_prob:.2f}" if ai_prob is not None else "-"
        sub = f"{sub_kind}:{sub_class}" if sub_kind else "-"
        print(f"{paper_id[:15]:16}{status:11}{chars:>8}  {prob:>8}  {(doc_class or '-')[:11]:12}  {sub}")
    print("-" * 78)
    n = len(scored)
    if n:
        flagged = [r for r in scored if (r[3] or 0) >= 0.5]
        print(f"{n} papers scored. {len(flagged)}/{n} ({100*len(flagged)/n:.0f}%) read as at least half AI-probable.")
    print(f"database: {DB_PATH}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "report":
        report()
        return
    if sys.argv[1] == "scan" and len(sys.argv) == 4:
        paper_id, path = sys.argv[2], sys.argv[3]
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        result = scan_paper(paper_id, text, os.environ.get("GPTZERO_API_KEY"))
        store(result)
        print(json.dumps({
            "paper_id": result.paper_id, "status": result.status,
            "ai_probability": result.ai_probability, "document_classification": result.document_classification,
            "subclass": (result.subclass.__dict__ if result.subclass else None),
            "note": result.note, "paragraphs_scored": len(result.paragraphs),
        }, indent=2))
        return
    print(__doc__)


if __name__ == "__main__":
    main()
