"""Condense the scan datasets into the small JSON the interface ships with.

The raw rows are several megabytes of transcripts and sentence scores. A phone
needs a few kilobytes: the counts, a handful of papers to read, and the links.
Every figure is counted here from datasets/, so the page never carries a number
somebody typed.

Usage: python scripts/build_ui_data.py
"""
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

D = Path("datasets")
OUT = Path("frontend/src/investigation.json")
FOLLOWUP = "channel-followup"
THRESHOLD = 0.5
SENTENCES_SHOWN = 10
FRAGMENT = 25


def load(path, key):
    unique = {}
    f = D / path
    if not f.exists():
        return []
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            unique[r[key]] = {**unique.get(r[key], {}), **r}
    return list(unique.values())


def num(v) -> int:
    return int(v) if str(v).isdigit() else 0


def machine(r) -> bool:
    return r.get("classification") in {"AI_ONLY", "MIXED"}


def clean(text: str, limit: int = 240) -> str:
    text = " ".join(str(text or "").replace("<i>", "").replace("</i>", "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


SHORT = {"proceedings of the national academy of sciences": "PNAS",
         "journal of clinical medicine": "J Clin Med"}


def short(journal) -> str:
    name = clean(journal, 60)
    for long, abbreviation in SHORT.items():
        if name.lower().startswith(long):
            return abbreviation
    return name[:1].upper() + name[1:]


def sentences(rows):
    """Pick the window of consecutive sentences that shows the most of both kinds.

    An all-machine or all-human text looks the same anywhere, so the opening lines
    do. A mixed one is only interesting at the seam, where flagged and clean lines
    sit next to each other, so the window slides to wherever that mix is richest.
    """
    scored = []
    for s in rows or []:
        text = clean(s.get("text"))
        # GPTZero splits on full stops, so "(e.g., ref. 12)." leaves "12 )." behind as
        # its own sentence with its own score. A score on five characters is noise, and
        # on screen it reads as if two characters were judged. Fold each fragment back
        # into the sentence it was cut from, which keeps that sentence's score.
        if scored and (len(text) < FRAGMENT or len(text.split()) < 3):
            scored[-1]["text"] = clean(scored[-1]["text"] + " " + text)
            continue
        scored.append({"text": text, "p": round(s.get("p") or 0, 2)})
    best, best_mix = 0, -1
    for i in range(max(1, len(scored) - SENTENCES_SHOWN + 1)):
        window = scored[i:i + SENTENCES_SHOWN]
        hot = sum(1 for s in window if s["p"] >= THRESHOLD)
        mix = min(hot, len(window) - hot)
        if mix > best_mix:
            best, best_mix = i, mix
    return {"shown": scored[best:best + SENTENCES_SHOWN], "offset": best, "total": len(scored),
            "flagged": sum(1 for s in scored if s["p"] >= THRESHOLD)}


def flag_kind(text: str) -> str:
    """What a flagged reference actually is. The answer explains the false alarms:
    the checker resolves journal articles best and everything else poorly."""
    low = text.lower()
    rules = [
        (r"nct\d{6,}|clinicaltrials|isrctn|trial regist", "Trial registrations"),
        (r"arxiv|biorxiv|medrxiv|preprint|proceedings|conference|symposium", "Preprints and conference papers"),
        (r"university press|\beds?\b\.?|editor|isbn|chapter|\bin:", "Books and chapters"),
        (r"world health|\bwho\b|institute of medicine|national academ|committee|guideline|"
         r"\bcdc\b|\bfda\b|ministry|report|organization|agency|society", "Guidelines and reports"),
        (r"https?://|www\.|available (from|at|online)|accessed|github", "Websites and datasets"),
    ]
    for pattern, label in rules:
        if re.search(pattern, low):
            return label
    return "Ordinary journal articles"


def main():
    papers = load("papers/results.jsonl", "pmcid")
    videos = load("videos/results.jsonl", "id")

    years = []
    for y in sorted({r["year"] for r in papers if r.get("year")}):
        group = [r for r in papers if r.get("year") == y]
        years.append({"year": y, "n": len(group), "machine": sum(1 for r in group if machine(r))})

    # Two machine-written papers and the human-written control, in that order.
    showcase = []
    for f in sorted((D / "showcase").glob("PMC*.json")):
        r = json.loads(f.read_text())
        showcase.append({"pmcid": r["pmcid"], "title": clean(r.get("title"), 140),
                         "journal": short(r.get("journal")), "year": r.get("year"),
                         "classification": r.get("classification"), "url": r.get("url"),
                         "ai": round(r.get("ai_probability") or 0, 3),
                         **sentences(r.get("sentences"))})
    showcase.sort(key=lambda r: (r["classification"] == "HUMAN_ONLY",
                                 r["flagged"] == r["total"], -r["total"]))
    humans = [r for r in showcase if r["classification"] == "HUMAN_ONLY"][:1]
    showcase = [r for r in showcase if r["classification"] != "HUMAN_ONLY"][:2] + humans

    laundered = sorted((r for r in papers if r.get("subclass") == "ai_paraphrased"),
                       key=lambda r: (-(r.get("year") or 0), -(r.get("ai_prob") or 0)))

    sample = [r for r in videos if r.get("query") != FOLLOWUP]
    chased = [r for r in videos if r.get("query") == FOLLOWUP]
    farms = {}
    for r in chased:
        name = r.get("uploader") or "unknown"
        total, flagged = farms.get(name, (0, 0))
        farms[name] = (total + 1, flagged + (1 if machine(r) else 0))
    stitched = sorted((r for r in videos if r.get("classification") == "MIXED"),
                      key=lambda r: -num(r.get("views")))[:3]

    checked = [r for r in papers if (r.get("bibliography") or {}).get("citations_checked")]
    bib = [r["bibliography"] for r in checked]

    # Every citation GPTZero called fake, looked up again by scripts/prove_crossref.py.
    # A journal article that cannot be found is unexplained. A book, report or website
    # that cannot be found is only outside what Crossref indexes.
    proof_file = D / "review/crossref-proof.json"
    proof = json.loads(proof_file.read_text()) if proof_file.exists() else {}
    recheck = proof.get("recheck") or []
    article = "Ordinary journal articles"
    missing = [r for r in recheck if r["now"] == "not_found" and flag_kind(r["text"]) == article]
    outside = [r for r in recheck if r["now"] == "uncheckable"
               or (r["now"] == "not_found" and flag_kind(r["text"]) != article)]
    # Only references a person checked by hand are named on the page. The automatic
    # "wrong authors" class also catches damaged records (Hen?ge for Henssge), so a
    # row counts as wrong only when the hand-checked file agrees.
    candidates_file = D / "review/candidates.json"
    by_hand = json.loads(candidates_file.read_text())["candidates"] if candidates_file.exists() else []
    wrong = [c for c in by_hand if c["kind"] == "wrong_authors"]
    judged = [r for r in proof.get("real", []) if r.get("new") is not None]
    built = [r for r in proof.get("fake", []) if r.get("new") is not None]

    data = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "threshold": THRESHOLD,
        "papers": {"n": len(papers), "machine": sum(1 for r in papers if machine(r)),
                   "years": years},
        "showcase": showcase,
        "flagged_papers": [{"title": clean(r.get("title"), 120), "journal": clean(r.get("journal"), 44),
                            "year": r.get("year"), "url": r.get("url"),
                            "ai": round(r.get("ai_prob") or 0, 2)}
                           for r in sorted((r for r in papers if r.get("classification") == "AI_ONLY"
                                            and r.get("prestige") and (r.get("ai_prob") or 0) >= 0.99),
                                           key=lambda r: (-(r.get("year") or 0), r.get("journal") or ""))
                           if any(k in (r.get("journal") or "").lower() for k in
                                  ("nature", "jama", "bmj", "lancet", "plos med", "national academy",
                                   "elife", "cell", "science"))][:12],
        "laundered": [{"title": clean(r.get("title"), 130), "journal": clean(r.get("journal"), 50),
                       "year": r.get("year"), "url": r.get("url")} for r in laundered],
        "videos": {
            "n": len(sample), "machine": sum(1 for r in sample if machine(r)),
            "views": sum(num(r.get("views")) for r in sample),
            "machine_views": sum(num(r.get("views")) for r in sample if machine(r)),
            "farms": [{"name": k, "n": n, "machine": m}
                      for k, (n, m) in sorted(farms.items(), key=lambda kv: -kv[1][0])],
            "stitched": [{"title": clean(r.get("title"), 110), "channel": r.get("uploader"),
                          "views": num(r.get("views")), "url": r.get("url"),
                          "subclass": r.get("subclass"), **sentences(r.get("sentences"))}
                         for r in stitched],
            "flagged": [{"title": clean(r.get("title"), 90), "channel": r.get("uploader"),
                         "views": num(r.get("views")), "url": r.get("url")}
                        for r in sorted((r for r in sample if r.get("classification") == "AI_ONLY"),
                                        key=lambda r: -num(r.get("views")))[:8]],
            "tells": [{"name": k, "count": v} for k, v in Counter(
                p["name"] for r in videos for p in r.get("patterns", [])).most_common(5)],
        },
        "citations": {
            "papers": len(checked),
            "checked": sum(b.get("citations_checked", 0) for b in bib),
            "flagged": sum(b.get("statuses", {}).get("fake", 0) for b in bib),
            "real": sum(1 for r in recheck if r["now"] in {"real", "wrong_authors"}) - len(wrong),
            "wrong_authors": len(wrong),
            "uncheckable": len(outside),
            "not_found": len(missing),
            "kinds": [{"name": k, "count": v}
                      for k, v in Counter(flag_kind(r["text"]) for r in recheck).most_common()],
            "candidates": [{"reference": c["reference"], "kind": c["kind"], "actual": c["actual"],
                            "journal": c["citing_journal"], "year": c["citing_year"],
                            "url": c["citing_url"]} for c in by_hand],
            "proof": {"real": len(judged), "real_found": sum(1 for r in judged if r["new"]),
                      "same_doi": sum(1 for r in judged if r["new"] and r.get("new_doi") == r.get("doi")),
                      "fake": len(built), "fake_cleared": sum(1 for r in built if r["new"]),
                      "fake_cleared_loose": sum(1 for r in built if r["old"])},
        },
        "subclasses": dict(Counter(r.get("subclass") for r in papers + videos if r.get("subclass"))),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"  papers {data['papers']['n']}, videos {data['videos']['n']}, "
          f"showcase {len(showcase)}, laundered {len(data['laundered'])}")


if __name__ == "__main__":
    main()
