"""Pull full sentence-level detail for a handful of papers, ready for the interface.

The batch scanner stores only the document verdict, because per-sentence data for
thousands of papers is a lot of JSON nobody reads. These few are different: they
are the ones shown on screen, so they carry every sentence and its score.

A human-written control is always included. Showing a 2026 paper from the same
journals that comes back clean is what separates "this detects machine writing"
from "this flags academic prose", and a judge will ask.

Usage: GPTZERO_API_KEY=... python scripts/showcase.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from defusedxml import ElementTree

KEY = os.environ.get("GPTZERO_API_KEY") or os.environ.get("KEY") or ""
if not KEY:
    sys.exit("Set GPTZERO_API_KEY, then re-run.")

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
DETECT = "https://api.gptzero.me/v2/predict/text"
SOURCE = Path(os.environ.get("PAPER_SCAN_DIR", "data/paper-scan")) / "results.jsonl"
OUT = Path("datasets/showcase")


def load():
    unique = {}
    for line in SOURCE.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            unique[r["pmcid"]] = {**unique.get(r["pmcid"], {}), **r}
    return list(unique.values())


def pick(rows):
    """One of each kind, newest and most confident first, prestige preferred."""
    def best(rule, n=1):
        hits = [r for r in rows if rule(r)]
        hits.sort(key=lambda r: (-(r.get("year") or 0), -(r.get("ai_prob") or 0)))
        return hits[:n]

    chosen = []
    chosen += best(lambda r: r["classification"] == "AI_ONLY" and r.get("prestige")
                   and (r.get("ai_prob") or 0) > 0.95, 2)
    chosen += best(lambda r: r["classification"] == "MIXED" and (r.get("year") or 0) >= 2025, 1)
    # The control, and the most important one on the page.
    chosen += best(lambda r: r["classification"] == "HUMAN_ONLY" and r.get("prestige")
                   and (r.get("year") or 0) >= 2025 and (r.get("ai_prob") or 1) < 0.001, 1)
    return chosen


async def full_detail(client, pmcid):
    r = await client.get(f"{EPMC}/{pmcid}/fullTextXML")
    body = ElementTree.fromstring(r.content).find(".//body")
    if body is None:
        return None
    prose = [" ".join(" ".join(p.itertext()).split()) for p in body.iter("p")]
    text = "\n\n".join([p for p in prose if len(p) > 80][:12])
    if len(text) < 400:
        return None
    g = await client.post(DETECT, headers={"x-api-key": KEY},
                          json={"document": text, "multilingual": False})
    g.raise_for_status()
    d = g.json()["documents"][0]
    probs = d.get("class_probabilities") or {}
    sub = (d.get("subclass") or {}).get(d.get("predicted_class"), {})
    return {
        "classification": d.get("document_classification"),
        "ai_probability": probs.get("ai"), "human_probability": probs.get("human"),
        "mixed_probability": probs.get("mixed"),
        "confidence": d.get("confidence_category"), "summary": d.get("result_message"),
        "subclass": sub.get("predicted_class"),
        "flagged_share": d.get("average_generated_prob"),
        "detector_version": d.get("version"),
        "sentences": [{"text": s.get("sentence", ""), "p": s.get("generated_prob")}
                      for s in (d.get("sentences") or [])],
        "paragraphs": [{"index": i, "p": p.get("completely_generated_prob"),
                        "sentences": p.get("num_sentences")}
                       for i, p in enumerate(d.get("paragraphs") or [])],
    }


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load()
    chosen = pick(rows)
    print(f"showcase picks: {len(chosen)}")
    saved = []
    async with httpx.AsyncClient(timeout=120) as client:
        for r in chosen:
            try:
                detail = await full_detail(client, r["pmcid"])
            except Exception as exc:
                print(f"  ! {r['pmcid']}: {type(exc).__name__}")
                continue
            if not detail:
                continue
            record = {"pmcid": r["pmcid"], "title": r.get("title"), "journal": r.get("journal"),
                      "year": r.get("year"), "prestige": r.get("prestige"), "url": r.get("url"),
                      **detail}
            (OUT / f"{r['pmcid']}.json").write_text(json.dumps(record, indent=1))
            saved.append(record)
            flagged = sum(1 for s in detail["sentences"] if (s["p"] or 0) >= 0.5)
            print(f"  {detail['classification']:<11} ai={detail['ai_probability']:.3f} "
                  f"{flagged}/{len(detail['sentences'])} sentences flagged  "
                  f"{(r.get('journal') or '')[:26]}  {r['pmcid']}")
    (OUT / "index.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k not in {"sentences", "paragraphs"}} for r in saved],
        indent=1))
    print(f"\nwrote {len(saved)} to {OUT}/ (plus index.json)")


if __name__ == "__main__":
    asyncio.run(main())
