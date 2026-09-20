"""Scan published papers for machine-written text and fabricated citations.

Europe PMC -> GPTZero detection on the paper's own prose, and GPTZero
bibliography scan on its reference list.

Two separate questions, never added together:
  1. Was this paper's text written by a model?
  2. Do the sources it cites actually exist?

Only papers published after CUTOFF are scanned, because a malformed citation in
a 2007 paper is human sloppiness, not fabrication. The gate is what makes a
positive result mean something.

Usage: GPTZERO_API_KEY=... python scripts/paper_scan.py [per_topic] [bib_budget]
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
BIB = "https://api.gptzero.me/v2/bibliography-scan/text"
OUT = Path(os.environ.get("PAPER_SCAN_DIR", "data/paper-scan"))
RESULTS = OUT / "results.jsonl"
CUTOFF = int(os.environ.get("YEAR_FLOOR", "2022"))  # the AI era gate
PRESTIGE_CUTOFF = int(os.environ.get("PRESTIGE_CUTOFF", "2024"))
# Set YEAR_FLOOR=2026 to sample only the most recent year. The machine-written
# rate is flat at 0% for 2022 and 2023, 2% for 2024 and 2025, then jumps in 2026,
# so the recent slice is where the sample most needs depth.
PRESTIGE_SHARE = 0.20  # at most a fifth of any batch, so the sample stays broad
MIN_CHARS = 400        # below this the detector has too little prose
BIB_PER_MINUTE = 9     # vendor limit is 10/min; stay under it
MIN_REFS = 12          # fewer than this is a stub, not a bibliography worth a call

TOPICS = [
    "seed oil inflammation", "berberine metabolic", "cortisol stress weight",
    "gut microbiome probiotic", "intermittent fasting metabolic", "vitamin D supplementation",
    "magnesium supplementation sleep", "ashwagandha cortisol", "sucralose metabolic",
    "aspartame safety", "raw milk pathogens", "insulin resistance diet",
    "collagen supplementation skin", "creatine supplementation", "omega 3 supplementation",
    "detoxification heavy metals", "fluoride neurodevelopment", "sunscreen safety",
    "nicotine cognition", "leaky gut intestinal permeability",
]


# High-impact venues first. A fabricated citation in the Lancet is a different
# story from one in a pay-to-publish journal, and these are the outlets whose
# editorial process is supposed to catch it.
PRESTIGE = [
    # Tier one: the venues where a fabricated citation is genuinely newsworthy.
    "Lancet", "BMJ", "JAMA", "Nature", "Nature Medicine", "Nature Communications",
    "Science", "Cell", "PNAS", "New England Journal of Medicine", "eLife",
    "JAMA Network Open", "PLoS Medicine", "Annals of Internal Medicine",
    "Cochrane Database Syst Rev",
    # Tier two: high volume, open access, still peer reviewed. Tier one drained at
    # roughly 2,800 papers, so these carry the sample from here.
    "Scientific Reports", "PLoS One", "Frontiers in Immunology", "Nutrients",
    "International Journal of Molecular Sciences", "Cureus", "Heliyon",
    "BMC Public Health", "BMC Medicine", "Frontiers in Nutrition",
    "Journal of Clinical Medicine", "Cells", "Biomedicines", "Antioxidants",
    "Frontiers in Pharmacology", "Medicina", "Healthcare", "Life",
    "Frontiers in Public Health", "BMJ Open", "Scientific Data", "iScience",
    # Tier three: high-volume venues with lighter editorial screening, which is
    # where the rate should be highest if the gradient is real.
    "Sensors", "Applied Sciences", "Sustainability", "Molecules", "Foods",
    "Microorganisms", "Diagnostics", "Pharmaceuticals", "Polymers", "Energies",
    "Frontiers in Psychology", "PeerJ", "F1000Research", "SAGE Open Medicine",
    "Medicine", "World Journal of Clinical Cases", "Annals of Medicine and Surgery",
]


async def discover(client, topic, limit, journal=None):
    """Open-access, full-text, post-cutoff papers. Full text gives us a bibliography.

    A journal scope drops the topic filter entirely. High-impact venues do not
    publish on seed oils or cortisol, so constraining them by consumer-wellness
    terms returned almost nothing. Any subject they publish is fair game.
    """
    if journal:
        query = (f'JOURNAL:"{journal}" AND OPEN_ACCESS:Y AND HAS_FT:Y '
                 f'AND (FIRST_PDATE:[{PRESTIGE_CUTOFF}-01-01 TO 2030-12-31])')
    else:
        query = (f'TITLE_ABS:("{topic}") AND OPEN_ACCESS:Y AND HAS_FT:Y '
                 f'AND (FIRST_PDATE:[{CUTOFF}-01-01 TO 2030-12-31])')
    r = await client.get(f"{EPMC}/search", params={
        "query": query + " sort_cited:y", "format": "json",
        "resultType": "core", "pageSize": limit})
    out = []
    for rec in r.json().get("resultList", {}).get("result", []):
        year = int((rec.get("firstPublicationDate") or "0")[:4] or 0)
        floor = PRESTIGE_CUTOFF if journal else CUTOFF
        if year < floor or not rec.get("pmcid"):
            continue
        out.append({"pmcid": rec["pmcid"], "pmid": rec.get("pmid"), "year": year,
                    "title": (rec.get("title") or "")[:160], "journal":
                    (rec.get("journalInfo") or {}).get("journal", {}).get("title", "")[:80],
                    "cited_by": rec.get("citedByCount", 0), "topic": topic,
                    "prestige": bool(journal),
                    "url": f"https://europepmc.org/article/PMC/{rec['pmcid']}"})
    return out


async def full_text(client, pmcid):
    """Return the paper's own prose and its reference list, separately."""
    r = await client.get(f"{EPMC}/{pmcid}/fullTextXML")
    root = ElementTree.fromstring(r.content)
    body = root.find(".//body")
    prose = []
    if body is not None:
        for p in body.iter("p"):
            t = " ".join(" ".join(p.itertext()).split())
            if len(t) > 80:
                prose.append(t)
    refs = [" ".join(" ".join(ref.itertext()).split()) for ref in root.iter("ref")]
    return "\n\n".join(prose[:14]), [x for x in refs if len(x) > 30]


async def detect(client, text):
    r = await client.post(DETECT, headers={"x-api-key": KEY},
                          json={"document": text[:48000], "multilingual": False})
    r.raise_for_status()
    d = r.json()["documents"][0]
    probs = d.get("class_probabilities") or {}
    sub = (d.get("subclass") or {}).get(d.get("predicted_class"), {})
    return {"classification": d.get("document_classification"), "ai_prob": probs.get("ai"),
            "mixed_prob": probs.get("mixed"), "confidence": d.get("confidence_category"),
            "subclass": sub.get("predicted_class"),
            "scripted_share": d.get("average_generated_prob")}


async def really_missing(client, text):
    """A 'fake' is only reported if we cannot find it ourselves.

    Measured false positive: GPTZero labelled NCT02693028 fake because its checker
    resolves journal articles, not trial registrations. Verify before accusing.
    """
    probe = " ".join(text.split())[:180]
    try:
        if "clinicaltrials" in text.lower() or "NCT" in text:
            r = await client.get("https://clinicaltrials.gov/api/v2/studies",
                                 params={"query.term": probe[:120], "pageSize": 1})
            if r.status_code == 200 and (r.json().get("studies") or []):
                return False, "resolved on ClinicalTrials.gov"
        r = await client.get("https://api.crossref.org/works",
                             params={"query.bibliographic": probe, "rows": 1,
                                     "select": "title,DOI"})
        if r.status_code == 200:
            items = (r.json().get("message") or {}).get("items") or []
            if items:
                return False, f"resolved on Crossref: {items[0].get('DOI')}"
    except Exception:
        return True, "verification unavailable"
    return True, "not found on Crossref or ClinicalTrials.gov"


async def bibliography(client, refs):
    r = await client.post(BIB, headers={"x-api-key": KEY},
                          json={"document": "\n".join(refs[:40])})
    r.raise_for_status()
    cits = r.json().get("bibliographic_citations") or []
    tally, flagged, unverified = {}, [], []
    for c in cits:
        e = c.get("citation_exists") or {}
        status = e.get("status") or "unknown"
        tally[status] = tally.get(status, 0) + 1
        # Only a real hallucination label counts. "minor issues" is not fabrication.
        if status == "fake" or e.get("hallucination_label"):
            text = str(c.get("text", ""))
            missing, note = await really_missing(client, text)
            entry = {"text": text[:200], "status": status, "label": e.get("hallucination_label"),
                     "why": str(e.get("hallucination_explanation") or "")[:240],
                     "verified_missing": missing, "verification": note}
            (flagged if missing else unverified).append(entry)
    return {"citations_checked": len(cits), "statuses": tally,
            "fabricated": flagged, "false_positives": unverified}


async def main(per_topic, bib_budget):
    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if RESULTS.exists():
        done = {json.loads(x)["pmcid"] for x in RESULTS.read_text().splitlines() if x.strip()}
    async with httpx.AsyncClient(timeout=200) as client:
        seen = set(done)
        elite, broad = [], []
        for journal in PRESTIGE:
            found = 0
            for p in await discover(client, "", 40, journal=journal):
                if p["pmcid"] not in seen:
                    seen.add(p["pmcid"])
                    elite.append(p)
                    found += 1
            print(f"  [prestige {PRESTIGE_CUTOFF}+] {journal}: +{found}  (pool {len(elite)})", flush=True)
        for topic in TOPICS:
            for p in await discover(client, topic, per_topic):
                if p["pmcid"] not in seen:
                    seen.add(p["pmcid"])
                    broad.append(p)
            print(f"  {topic}: pool {len(broad)}", flush=True)

        # Interleave so prestige never exceeds its share of any stretch of the run.
        every = max(1, round(1 / PRESTIGE_SHARE))
        papers, ei, bi = [], 0, 0
        while ei < len(elite) or bi < len(broad):
            if len(papers) % every == 0 and ei < len(elite):
                papers.append(elite[ei])
                ei += 1
            elif bi < len(broad):
                papers.append(broad[bi])
                bi += 1
            elif ei < len(elite):
                papers.append(elite[ei])
                ei += 1
        print(f"\n  pools: {len(elite)} prestige + {len(broad)} broad, "
              f"interleaved 1 in {every}", flush=True)
        print(f"\n{len(papers)} new papers, {len(done)} already scanned\n", flush=True)

        # Two passes, because the limits are wildly different. Detection is
        # 30,000/hour, bibliography is 10/minute. Running them together meant
        # waiting 6.7 seconds per paper for the headline number. So: score every
        # paper first, then spend the citation budget afterwards.
        scored = []
        for i, p in enumerate(papers, 1):
            try:
                prose, refs = await full_text(client, p["pmcid"])
            except Exception as exc:
                print(f"[{i}/{len(papers)}] ! full text {p['pmcid']}: {type(exc).__name__}", flush=True)
                continue
            if len(prose) < MIN_CHARS:
                continue
            row = {**p, "prose_chars": len(prose), "references": len(refs)}
            try:
                row.update(await detect(client, prose))
            except Exception as exc:
                print(f"[{i}/{len(papers)}] ! detect {p['pmcid']}: {type(exc).__name__}", flush=True)
                continue
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")
            scored.append((row, refs))
            flag = "<<<" if row["classification"] != "HUMAN_ONLY" else ""
            print(f"[{i}/{len(papers)}] {row['classification']:<11} ai={row['ai_prob']:.3f} "
                  f"{p['year']} {'PRESTIGE' if p.get('prestige') else 'broad   '} "
                  f"{p['title'][:44]} {flag}", flush=True)

        print(f"\n--- detection done on {len(scored)} papers, now citations "
              f"(budget {bib_budget}, 9/min) ---\n", flush=True)

        # Machine-written papers first: a fabricated citation matters most there.
        order = sorted(scored, key=lambda x: (x[0]["classification"] == "HUMAN_ONLY",
                                              not x[0].get("prestige")))
        done_bib = 0
        for row, refs in order:
            if done_bib >= bib_budget or len(refs) < MIN_REFS:
                continue
            try:
                bib = await bibliography(client, refs)
            except Exception as exc:
                print(f"  ! bibliography {row['pmcid']}: {type(exc).__name__}", flush=True)
                continue
            done_bib += 1
            with RESULTS.open("a") as f:
                f.write(json.dumps({**row, "bibliography": bib}) + "\n")
            fab = len(bib.get("fabricated", []))
            mark = "  *** FABRICATED ***" if fab else ""
            print(f"  [{done_bib}/{bib_budget}] {row['pmcid']} refs={bib['citations_checked']} "
                  f"fabricated={fab} fp={len(bib.get('false_positives', []))} "
                  f"{row['title'][:34]}{mark}", flush=True)
            await asyncio.sleep(60 / BIB_PER_MINUTE)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10,
                     int(sys.argv[2]) if len(sys.argv) > 2 else 25))
