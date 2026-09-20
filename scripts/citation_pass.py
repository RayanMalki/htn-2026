"""Check citations in papers already scored by paper_scan.py. Runs forever.

Detection is 30,000/hour, bibliography is 10/minute, so the two cannot share a
loop without the slow one throttling the fast one. This worker does only the slow
half, and it picks its order deliberately:

  1. machine-written papers, prestige venues first
  2. machine-written papers, everywhere else
  3. everything else

A fabricated citation inside a machine-written paper is the case worth finding,
so the budget is spent there first rather than on whatever came back alphabetically.

It rescans for new work after each lap, so it can run alongside detection and will
pick up papers as they are scored.

Usage: GPTZERO_API_KEY=... python scripts/citation_pass.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from defusedxml import ElementTree
from verify import UNCHECKABLE, Unavailable, crossref_items, title_agrees

KEY = os.environ.get("GPTZERO_API_KEY") or os.environ.get("KEY") or ""
if not KEY:
    sys.exit("Set GPTZERO_API_KEY, then re-run.")

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
BIB = "https://api.gptzero.me/v2/bibliography-scan/text"
OUT = Path(os.environ.get("PAPER_SCAN_DIR", "data/paper-scan"))
RESULTS = OUT / "results.jsonl"
PER_MINUTE = 9
MIN_REFS = 12


def load():
    unique = {}
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            unique[r["pmcid"]] = {**unique.get(r["pmcid"], {}), **r}
    return unique


def rank(r):
    """Machine-written first, prestige ahead of broad inside each group.

    This is the cascade: detection says a paper carries machine-written text, and
    that is what earns it the expensive checks. The citation scan and the claim
    stance check both come back in the same response, so a hit on the text buys
    the answer to "are its sources real" and "do those sources say what it claims"
    at no extra cost.
    """
    return (r.get("classification") == "HUMAN_ONLY", not r.get("prestige"), -r.get("year", 0))


async def references(client, pmcid):
    r = await client.get(f"{EPMC}/{pmcid}/fullTextXML")
    root = ElementTree.fromstring(r.content)
    refs = [" ".join(" ".join(x.itertext()).split()) for x in root.iter("ref")]
    body = root.find(".//body")
    prose = []
    if body is not None:
        for para in body.iter("p"):
            t = " ".join(" ".join(para.itertext()).split())
            if len(t) > 80:
                prose.append(t)
    return [x for x in refs if len(x) > 30], "\n\n".join(prose[:10])


async def resolvable(client, text):
    """Return True if we can find the citation ourselves, so a fake label is wrong.

    The matching lives in verify.py and is measured by prove_crossref.py: against
    30 known-real and 20 known-fake references it finds 28 of the real ones and
    clears none of the fakes. The rule it replaced cleared 11 of the 20 fakes.
    """
    probe = " ".join(text.split())[:180]
    low = text.lower()
    if sum(k in low for k in UNCHECKABLE) >= 2:
        return True, "book chapter or thesis: outside Crossref coverage, not checkable"
    try:
        if "clinicaltrials" in low or "NCT" in text:
            r = await client.get("https://clinicaltrials.gov/api/v2/studies",
                                 params={"query.term": probe[:120], "pageSize": 1})
            if r.status_code == 200 and (r.json().get("studies") or []):
                return True, "resolved on ClinicalTrials.gov"
        for item in await crossref_items(client, text):
            if title_agrees(item, text):
                title = " ".join(item.get("title") or [])
                return True, f"resolved on Crossref: {item.get('DOI')} ({title[:60]})"
        return False, "Crossref holds no record whose full title matches"
    except Unavailable:
        return False, "verification unavailable: Crossref did not answer"
    except Exception:
        return False, "verification unavailable"


def read_claims(body):
    """The third question the same response answers, and the one closest to what
    people mean by hallucination: is this claim cited at all, and does the source
    it cites actually support it? Captured verbatim, stance included.
    """
    out = []
    for c in body.get("claims") or []:
        cited = c.get("is_cited_in_bibliography") or {}
        stance = c.get("agree_with_citation") or {}
        out.append({"text": str(c.get("text", ""))[:400],
                    "claim_type": c.get("claim_type"),
                    "check_worthy": cited.get("check_worthy"),
                    "is_cited": cited.get("is_cited"),
                    "why_needs_citation": str(cited.get("justification") or "")[:240],
                    "stance": stance.get("stance"),
                    "stance_why": str(stance.get("justification") or "")[:240]})
    return out[:40]


async def scan(client, refs, prose=""):
    # Sending the prose alongside the references is what makes the claims array
    # come back populated. References alone give citations only.
    document = (prose[:20000] + "\n\n" + "\n".join(refs[:40])) if prose else "\n".join(refs[:40])
    r = await client.post(BIB, headers={"x-api-key": KEY}, json={"document": document})
    r.raise_for_status()
    body = r.json()
    tally, fabricated, false_positives = {}, [], []
    for c in body.get("bibliographic_citations") or []:
        e = c.get("citation_exists") or {}
        status = e.get("status") or "unknown"
        tally[status] = tally.get(status, 0) + 1
        if status == "fake" or e.get("hallucination_label"):
            text = str(c.get("text", ""))
            found, note = await resolvable(client, text)
            entry = {"text": text[:600], "status": status, "label": e.get("hallucination_label"),
                     "why": str(e.get("hallucination_explanation") or "")[:240],
                     "verified_missing": not found, "verification": note}
            (false_positives if found else fabricated).append(entry)
    claims = read_claims(body)
    uncited = [c for c in claims if c.get("check_worthy") and not c.get("is_cited")]
    unsupported = [c for c in claims if c.get("stance") in
                   {"contradict", "partial contradict", "strongly contradict", "slightly disagree"}]
    return {"citations_checked": sum(tally.values()), "statuses": tally,
            "fabricated": fabricated, "false_positives": false_positives,
            "claims": claims, "claims_checked": len(claims),
            "uncited_checkworthy": len(uncited), "unsupported_by_citation": len(unsupported)}


async def main():
    lap = 0
    async with httpx.AsyncClient(timeout=200) as client:
        while True:
            lap += 1
            papers = load()
            todo = sorted((r for r in papers.values() if not r.get("bibliography")), key=rank)
            done = sum(1 for r in papers.values() if r.get("bibliography"))
            machine = sum(1 for r in todo if r.get("classification") != "HUMAN_ONLY")
            print(f"\n=== lap {lap}: {len(todo)} to check ({machine} machine-written first), "
                  f"{done} already done ===", flush=True)
            if not todo:
                print("  nothing new, waiting for detection to add more", flush=True)
                await asyncio.sleep(120)
                continue
            for i, p in enumerate(todo, 1):
                try:
                    refs, prose = await references(client, p["pmcid"])
                except Exception as exc:
                    print(f"[{i}/{len(todo)}] ! refs {p['pmcid']}: {type(exc).__name__}", flush=True)
                    continue
                if len(refs) < MIN_REFS:
                    # Record the attempt so the next lap does not retry a stub forever.
                    with RESULTS.open("a") as f:
                        f.write(json.dumps({**p, "bibliography": {
                            "citations_checked": 0, "statuses": {}, "fabricated": [],
                            "false_positives": [], "note": "too few references"}}) + "\n")
                    continue
                try:
                    bib = await scan(client, refs, prose)
                except Exception as exc:
                    print(f"[{i}/{len(todo)}] ! scan {p['pmcid']}: {type(exc).__name__}", flush=True)
                    await asyncio.sleep(10)
                    continue
                with RESULTS.open("a") as f:
                    f.write(json.dumps({**p, "bibliography": bib}) + "\n")
                fab = len(bib["fabricated"])
                mark = "   *** UNRESOLVED FABRICATION ***" if fab else ""
                print(f"[{i}/{len(todo)}] {p['classification']:<11} {p['year']} "
                      f"refs={bib['citations_checked']:<3} fake={bib['statuses'].get('fake', 0)} "
                      f"unresolved={fab} claims={bib['claims_checked']} "
                      f"uncited={bib['uncited_checkworthy']} "
                      f"contradicted={bib['unsupported_by_citation']} "
                      f"{p['title'][:28]}{mark}", flush=True)
                await asyncio.sleep(60 / PER_MINUTE)


if __name__ == "__main__":
    asyncio.run(main())
