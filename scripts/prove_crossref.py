"""Measure whether the Crossref check can be trusted, against answers we already know.

A verifier that says "real" to everything looks perfect until you feed it a fake.
So this feeds it both:

  real   references lifted from published papers whose XML carries the DOI. The
         DOI is removed from the text before the check, then used to mark it. A
         pass means the check found the same DOI on its own.
  fake   chimeras built from those same references (authors of one, half the
         title of one, half of another) plus citations invented from nothing.
         These cannot exist, so any "resolved" is a false clearance.

Two rules are scored on the same Crossref responses: the old one (any 25 shared
characters) and the strict one now used in citation_pass.py.

Usage: python scripts/prove_crossref.py            the measurement
       python scripts/prove_crossref.py --recheck  also re-verify every flagged citation
"""
import asyncio
import json
import random
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from defusedxml import ElementTree

sys.path.insert(0, str(Path(__file__).parent))
from verify import UNCHECKABLE, Unavailable, authors_agree, crossref_items, title_agrees, words  # noqa: E402

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
RESULTS = Path("datasets/papers/results.jsonl")
REPORT = Path("datasets/review/crossref-proof.json")
SEED = 20260920

INVENTED = [
    "Hartwell J, Nakamura P. Deep residual attention for seven-class glioma staging from handwriting samples. Neuroinformatics. 2025;23(2):114-129.",
    "Lindqvist A, Barros M, Chen W. Fermented root beer polyphenols reverse mitochondrial ageing in zebrafish. Cell Metab. 2023;35(4):611-624.",
    "Okafor T, Malki R. Transdermal caffeine absorption predicts sleep debt recovery in adolescent swimmers. J Sleep Res. 2024;33(2):e14122.",
    "Petrov D, Hughes S, Amari K. Sucralose exposure and fascia stiffness in recreational runners: a randomized crossover trial. BMJ Open. 2024;14(6):e081234.",
    "Wang L, Gupta R. Explainable gradient boosting for early detection of Parkinson's disease from smartwatch typing cadence. NPJ Digit Med. 2025;8(1):212.",
    "Morales F, Schmidt H, Lee Y. Raw milk consumption and gut virome diversity in urban adults: a five-year cohort. Lancet Microbe. 2024;5(3):e201-e210.",
    "Kim S, Park J, Choi M. SHAP-guided graph transformers for four-stage dementia grading with retinal imaging. J Alzheimers Dis. 2025;98(1):77-91.",
    "Rossi G, Tanaka M. Seed oil intake and telomere attrition in postmenopausal women: a Mendelian randomization study. JAMA Netw Open. 2025;8(2):e2461234.",
]


def old_rule(items, text):
    low = text.lower()
    for item in items:
        title = " ".join(item.get("title") or [])
        if not title:
            continue
        size = SequenceMatcher(None, title.lower()[:120], low[:400]).find_longest_match(
            0, min(120, len(title)), 0, min(400, len(low))).size
        if size >= 25:
            return item
    return None


def new_rule(items, text):
    for item in items:
        if title_agrees(item, text):
            return item
    return None


async def known_real(client, want):
    """References whose DOI is printed in the paper's own XML."""
    rows = {}
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["pmcid"]] = r
    rng = random.Random(SEED)
    pool, out = rng.sample(sorted(rows), 40), []
    for pmcid in pool:
        if len(out) >= want:
            break
        try:
            r = await client.get(f"{EPMC}/{pmcid}/fullTextXML")
            root = ElementTree.fromstring(r.content)
        except Exception:
            continue
        refs = []
        for ref in root.iter("ref"):
            doi = next((e.text for e in ref.iter("pub-id") if e.get("pub-id-type") == "doi" and e.text), None)
            title = next((" ".join(" ".join(e.itertext()).split()) for e in ref.iter("article-title")), None)
            if not doi or not title or len(title.split()) < 6:
                continue
            text = " ".join(" ".join(ref.itertext()).split())
            text = re.sub(r"(https?://(dx\.)?doi\.org/)?" + re.escape(doi), "", text, flags=re.I)
            text = re.sub(r"\b(doi|pmid|pmcid)\b:?\s*\S*", "", text, flags=re.I).strip()
            refs.append({"text": text, "doi": doi.lower().strip(), "title": title, "from": pmcid})
        out += rng.sample(refs, min(5, len(refs)))
    return out[:want]


def chimeras(real, want):
    """Real authors, half of one real title, half of another. Cannot exist."""
    rng = random.Random(SEED + 1)
    out = []
    for _ in range(want):
        a, b = rng.sample(real, 2)
        ta, tb = a["title"].split(), b["title"].split()
        title = " ".join(ta[: len(ta) // 2] + tb[len(tb) // 2:])
        authors = a["text"].split(a["title"][:20])[0][:90].strip() or "Smith J, Lee K."
        out.append({"text": f"{authors} {title}. {rng.choice(['PLoS One', 'Sci Rep', 'BMJ Open'])}. "
                            f"{rng.choice([2023, 2024, 2025])}.", "doi": None, "title": title})
    return out


async def judge(client, case, sem):
    async with sem:
        try:
            items = await crossref_items(client, case["text"])
        except Unavailable:
            return {**case, "old": None, "new": None, "new_doi": None, "old_title": None}
    old, new = old_rule(items, case["text"]), new_rule(items, case["text"])
    return {**case, "old": bool(old), "new": bool(new),
            "new_doi": (new or {}).get("DOI", "").lower() or None,
            "old_title": " ".join((old or {}).get("title") or [])[:80] or None}


def table(name, rows, real):
    skipped = sum(1 for r in rows if r["new"] is None)
    rows = [r for r in rows if r["new"] is not None]
    if skipped:
        print(f"  {name:<10} {skipped} not answered by Crossref, left out")
    n = len(rows)
    for rule in ("old", "new"):
        hits = sum(1 for r in rows if r[rule])
        label = "found (correct)" if real else "cleared (WRONG)"
        print(f"  {name:<10} {rule} rule: {hits:>2}/{n} {label}")


async def recheck(client, sem):
    """Every citation GPTZero called fake, judged again by the strict rule."""
    rows = {}
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["pmcid"]] = {**rows.get(r["pmcid"], {}), **r}
    flagged = []
    for r in rows.values():
        b = r.get("bibliography") or {}
        for kind in ("false_positives", "fabricated"):
            for f in b.get(kind, []):
                flagged.append({"pmcid": r["pmcid"], "paper": r.get("title"), "journal": r.get("journal"),
                                "year": r.get("year"), "url": r.get("url"),
                                "classification": r.get("classification"),
                                "text": f["text"], "was": kind, "why": f.get("why")})

    # The scan stored the first 200 characters of each reference. A long author
    # list pushes the title past that cut, so fetch the whole reference again.
    full = {}
    for pmcid in sorted({f["pmcid"] for f in flagged}):
        try:
            r = await client.get(f"{EPMC}/{pmcid}/fullTextXML")
            full[pmcid] = [" ".join(" ".join(x.itertext()).split())
                           for x in ElementTree.fromstring(r.content).iter("ref")]
        except Exception:
            full[pmcid] = []
    for f in flagged:
        key = " ".join(words(f["text"])[:9])
        f["text"] = next((t for t in full[f["pmcid"]] if " ".join(words(t)[:9]) == key), f["text"])

    async def one(f):
        low = f["text"].lower()
        if sum(k in low for k in UNCHECKABLE) >= 2:
            return {**f, "now": "uncheckable", "doi": None}
        async with sem:
            try:
                items = await crossref_items(client, f["text"])
            except Unavailable:
                return {**f, "now": "unavailable", "doi": None, "nearest": None}
        hit = new_rule(items, f["text"])
        state = "not_found"
        if hit:
            state = "wrong_authors" if authors_agree(hit, f["text"]) is False else "real"
        return {**f, "now": state, "doi": (hit or {}).get("DOI"),
                "record_authors": [a.get("family") for a in (hit or {}).get("author", [])[:6]],
                "nearest": " ".join(items[0].get("title") or [""])[:90] if items else None}

    return await asyncio.gather(*(one(f) for f in flagged))


async def audit(client):
    """Re-judge the rows already marked real, by DOI, without repeating the search."""
    report = json.loads(REPORT.read_text())
    for r in report.get("recheck", []):
        if r["now"] != "real" or not r.get("doi"):
            continue
        got = await client.get(f"https://api.crossref.org/works/{r['doi']}")
        if got.status_code != 200:
            continue
        item = got.json()["message"]
        r["record_authors"] = [a.get("family") for a in item.get("author", [])[:6]]
        if authors_agree(item, r["text"]) is False:
            r["now"] = "wrong_authors"
            print(f"  wrong authors  {r['pmcid']}  {r['text'][:90]}\n"
                  f"      the record lists: {', '.join(x or '?' for x in r['record_authors'])}")
        await asyncio.sleep(0.3)
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    rows = report.get("recheck", [])
    print({k: sum(1 for r in rows if r["now"] == k)
           for k in ("real", "wrong_authors", "uncheckable", "not_found")})


async def main():
    if "--audit" in sys.argv:
        async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "medbot-citation-check/1.0"}) as client:
            await audit(client)
        return
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "medbot-citation-check/1.0"}) as client:
        real = await known_real(client, 30)
        fake = chimeras(real, 12) + [{"text": t, "doi": None, "title": t} for t in INVENTED]
        print(f"known real: {len(real)} references with a printed DOI (DOI removed before the check)")
        print(f"known fake: {len(fake)} (12 chimeras of those references, {len(INVENTED)} invented)\n")
        real_rows = await asyncio.gather(*(judge(client, c, sem) for c in real))
        fake_rows = await asyncio.gather(*(judge(client, c, sem) for c in fake))

        table("real", real_rows, True)
        table("fake", fake_rows, False)
        same = sum(1 for r in real_rows if r["new"] and r["new_doi"] == r["doi"])
        print(f"\n  strict rule returned the SAME DOI the paper printed: {same}/{sum(1 for r in real_rows if r['new'])}")
        print("\n  three real ones, as found:")
        for r in [r for r in real_rows if r["new"]][:3]:
            print(f"    {r['title'][:70]}\n      printed {r['doi']}\n      found   {r['new_doi']}")
        wrong = [r for r in fake_rows if r["old"]]
        if wrong:
            print("\n  fakes the OLD rule cleared, and what it matched them to:")
            for r in wrong[:4]:
                print(f"    fake: {r['title'][:70]}\n      matched: {r['old_title']}")

        report = {"seed": SEED, "real": real_rows, "fake": fake_rows}
        if "--recheck" in sys.argv:
            rows = await recheck(client, sem)
            report["recheck"] = rows
            flips = [r for r in rows if r["was"] == "false_positives" and r["now"] == "not_found"]
            print(f"\nrecheck of {len(rows)} flagged citations with the strict rule:")
            for state in ("real", "wrong_authors", "uncheckable", "not_found", "unavailable"):
                print(f"  {state:<12} {sum(1 for r in rows if r['now'] == state)}")
            print(f"  previously cleared, now not found: {len(flips)}")
            for r in flips:
                print(f"    {r['pmcid']} {r['classification']:<10} {r['text'][:100]}\n"
                      f"        nearest on Crossref: {r['nearest']}")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
