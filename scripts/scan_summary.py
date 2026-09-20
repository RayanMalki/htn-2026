"""Summarise scan/results.jsonl. Run any time; it reads whatever exists so far.

Usage: python scripts/scan_summary.py [path-to-results.jsonl]

Authorship and citation integrity are different questions and are reported
separately. A machine-written script is not a hallucination, and a paper with a
broken citation was not necessarily written by a model.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROWS = Path(sys.argv[1] if len(sys.argv) > 1 else "data/slop-scan/results.jsonl")
FOLLOWUP = "channel-followup"


def num(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load():
    unique = {}
    for line in ROWS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            unique[r["id"]] = r
    return list(unique.values())


def machine(r) -> bool:
    return r.get("classification") in {"AI_ONLY", "MIXED"}


def bar(n, total, width=28) -> str:
    filled = 0 if not total else round(n / total * width)
    return "#" * filled + "." * (width - filled)


def main():
    rows = load()
    sample = [r for r in rows if r.get("query") != FOLLOWUP]
    chased = [r for r in rows if r.get("query") == FOLLOWUP]

    print(f"\n{'=' * 66}\nSCAN SUMMARY  ({len(rows)} unique videos)\n{'=' * 66}")

    for label, group in (("TOPIC SAMPLE (a population rate)", sample),
                         ("CHANNEL FOLLOW-UP (not a rate: chosen by pulling a thread)", chased)):
        if not group:
            continue
        flagged = [r for r in group if machine(r)]
        views_all = sum(num(r.get("views")) for r in group)
        views_ai = sum(num(r.get("views")) for r in flagged)
        print(f"\n{label}")
        print(f"  videos            {len(group)}")
        print(f"  machine-written   {len(flagged)}  ({len(flagged) / len(group) * 100:.1f}%)  "
              f"{bar(len(flagged), len(group))}")
        print(f"  their share of views  {views_ai:,} of {views_all:,}"
              f"  ({views_ai / views_all * 100:.4f}%)" if views_all else "  views: unknown")

    print(f"\n{'-' * 66}\nHOW THE MACHINE-WRITTEN ONES WERE MADE (subclass)")
    subs = Counter(r.get("subclass") for r in rows if r.get("subclass"))
    total_sub = sum(subs.values()) or 1
    meaning = {"pure_ai": "straight out of a model",
               "ai_paraphrased": "run through a humaniser to evade detection",
               "concatenated": "human and machine blocks stitched together",
               "polished": "a person wrote it, a model smoothed it"}
    for name, count in subs.most_common():
        print(f"  {name:<16} {count:>4}  ({count / total_sub * 100:4.1f}%)  {meaning.get(name, '')}")
    if not subs:
        print("  none yet")

    print(f"\n{'-' * 66}\nCONFIDENCE OF THE DETECTOR")
    print("  " + "  ".join(f"{k}={v}" for k, v in
                           Counter(r.get("confidence") for r in rows).most_common()))

    print(f"\n{'-' * 66}\nWRITING TELLS (GPTZero AI Patterns)")
    pats = Counter(p["name"] for r in rows for p in r.get("patterns", []))
    with_any = sum(1 for r in rows if r.get("patterns"))
    print(f"  videos with at least one tell: {with_any} of {len(rows)}")
    for name, count in pats.most_common():
        print(f"    {name:<24} {count:>4}  {bar(count, max(pats.values()) if pats else 1, 20)}")
    if not pats:
        print("    none yet")

    print(f"\n{'-' * 66}\nBY TOPIC (topic sample only, worst first)")
    by_topic = defaultdict(lambda: [0, 0])
    for r in sample:
        by_topic[r.get("query", "?")][0] += 1
        if machine(r):
            by_topic[r["query"]][1] += 1
    ranked = sorted(by_topic.items(), key=lambda kv: (-kv[1][1] / kv[1][0], -kv[1][0]))
    for topic, (n, flagged) in ranked[:12]:
        if flagged:
            print(f"  {flagged}/{n:<3} {topic}")
    if not any(f for _, (_, f) in ranked):
        print("  no machine-written videos in any topic yet")

    print(f"\n{'-' * 66}\nWORST OFFENDERS (machine-written, by reach)")
    offenders = sorted((r for r in rows if machine(r)), key=lambda r: -num(r.get("views")))
    for r in offenders[:10]:
        tells = ", ".join(sorted({p["name"] for p in r.get("patterns", [])})) or "no tells"
        print(f"  {num(r.get('views')):>8,} views  {(r.get('uploader') or '?')[:26]:<26} {tells[:34]}")
        print(f"            {r.get('url')}")

    print(f"\n{'-' * 66}\nNOT MEASURED HERE")
    print("  Citation integrity is a separate check (GPTZero bibliography scan) and")
    print("  runs against papers we cite, not against these videos. A machine-written")
    print("  script is not a hallucination, and the two must not be added together.")
    print()


if __name__ == "__main__":
    main()
