"""Extract the cases that need a human eye into readable review files.

Three lists, because three different judgements are being asked for:

  mixed-videos.md      partly machine-written. The boundary between a creator's
                       own words and a script is where the classifier is least
                       certain and most consequential, so every sentence is shown
                       with its score.
  paraphrased.md       machine text pushed through a humaniser. A different and
                       more deliberate act than reading a script.
  flagged-citations.md citations GPTZero called fake that we also failed to
                       resolve on Crossref or ClinicalTrials.gov. Anything we did
                       resolve is listed separately as a false positive, so the
                       reviewer can see what the detector got wrong too.

Usage: python scripts/review_lists.py
"""
import json
from pathlib import Path

VIDEOS = Path("datasets/videos/results.jsonl")
PAPERS = Path("datasets/papers/results.jsonl")
OUT = Path("datasets/review")
THRESHOLD = 0.5


def load(path, key):
    if not path.exists():
        return []
    unique = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            # Later rows win: the citation pass rewrites a paper row with its
            # bibliography attached.
            prior = unique.get(r[key], {})
            unique[r[key]] = {**prior, **r}
    return list(unique.values())


def video_block(r) -> str:
    lines = [f"### {r.get('title', '?')}", "",
             f"- **Channel** {r.get('uploader', '?')}",
             f"- **Views** {r.get('views', '?')}",
             f"- **Verdict** `{r.get('classification')}` · subclass `{r.get('subclass')}`"
             f" · ai={r.get('ai_prob')} mixed={r.get('mixed_prob')}",
             f"- **Confidence** {r.get('confidence')}",
             f"- <{r.get('url')}>", ""]
    tells = {p["name"] for p in r.get("patterns", [])}
    if tells:
        lines += [f"- **Tells** {', '.join(sorted(tells))}", ""]
    lines += ["| score | sentence |", "|---|---|"]
    for s in r.get("sentences", []):
        p = s.get("p") or 0
        mark = "**" if p >= THRESHOLD else ""
        text = (s.get("text") or "").replace("|", "\\|")
        lines.append(f"| {mark}{p:.2f}{mark} | {text} |")
    return "\n".join(lines) + "\n"


def citation_block(r) -> str:
    bib = r.get("bibliography") or {}
    lines = [f"### {r.get('title', '?')}", "",
             f"- **Journal** {r.get('journal', '?')} · {r.get('year')}"
             f"{' · PRESTIGE' if r.get('prestige') else ''}",
             f"- **The paper itself** `{r.get('classification')}` ai={r.get('ai_prob')}",
             f"- **Citations checked** {bib.get('citations_checked')} · "
             f"statuses {bib.get('statuses')}",
             f"- <{r.get('url')}>", ""]
    for f in bib.get("fabricated", []):
        lines += ["**Flagged, and we could not resolve it either:**", "",
                  f"> {f.get('text', '')}", "",
                  f"- verification: {f.get('verification')}",
                  f"- detector said: {f.get('why') or f.get('status')}", ""]
    for f in bib.get("false_positives", []):
        lines += ["*Detector called this fake, but we resolved it. Not a fabrication:*", "",
                  f"> {f.get('text', '')}", "",
                  f"- {f.get('verification')}", ""]
    return "\n".join(lines)


def write(name, title, intro, blocks):
    OUT.mkdir(parents=True, exist_ok=True)
    body = f"# {title}\n\n{intro}\n\n**{len(blocks)} to review.**\n\n"
    body += "\n---\n\n".join(blocks) if blocks else "_Nothing flagged yet._\n"
    (OUT / name).write_text(body)
    print(f"  {name:<24} {len(blocks)}")


def main():
    videos = load(VIDEOS, "id")
    papers = load(PAPERS, "pmcid")
    print("review lists written to datasets/review/")

    mixed = [r for r in videos if r.get("classification") == "MIXED"]
    write("mixed-videos.md", "Partly machine-written videos",
          "Neither fully human nor fully machine. Every sentence is shown with its "
          "score, bold at or above 0.5. Check whether the split the detector drew "
          "matches where the creator actually went off-script.",
          [video_block(r) for r in sorted(mixed, key=lambda r: -(r.get("mixed_prob") or 0))])

    para = [r for r in videos if r.get("subclass") == "ai_paraphrased"]
    write("paraphrased.md", "Machine text run through a humaniser",
          "The detector believes these were generated and then reworded to evade "
          "detection. That is a more deliberate act than reading a script, so it "
          "deserves a look before anyone says it out loud.",
          [video_block(r) for r in para])

    flagged = [r for r in papers if (r.get("bibliography") or {}).get("fabricated")]
    fps = [r for r in papers if (r.get("bibliography") or {}).get("false_positives")
           and not (r.get("bibliography") or {}).get("fabricated")]
    scanned = [r for r in papers if r.get("bibliography")]
    checked = sum(r["bibliography"].get("citations_checked", 0) for r in scanned)
    said_fake = sum(r["bibliography"].get("statuses", {}).get("fake", 0) for r in scanned)
    resolved = sum(len(r["bibliography"].get("false_positives", [])) for r in scanned)
    write("flagged-citations.md", "Citation check",
          f"{checked} citations checked across {len(scanned)} papers. GPTZero called "
          f"{said_fake} of them fake. We resolved {resolved} of those ourselves on "
          f"Crossref or ClinicalTrials.gov, leaving **{len(flagged)} unresolved**.\n\n"
          "Only the unresolved ones are fabrication candidates, and even those need "
          "checking by hand before the word is used in public. The resolved ones are "
          "listed after them because the detector's error rate is part of the finding.",
          [citation_block(r) for r in flagged] + [citation_block(r) for r in fps])


if __name__ == "__main__":
    main()
