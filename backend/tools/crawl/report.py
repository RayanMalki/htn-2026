"""
What is in crawl/transcripts.db, and when GPTZero scores exist, what share of the
transcripts read as machine written. Uses the same threshold as the paper scanner
(at least 0.5 AI probability) so the two numbers can sit next to each other.

Usage: python3 report.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "transcripts.db"


def main() -> None:
    if not DB_PATH.exists():
        print("no database yet, run scan_batch.py first")
        return
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT author, views, duration, transcript_chars, gptzero_status, ai_probability,
               document_classification, subclass, route, url
        FROM transcripts ORDER BY views DESC NULLS LAST
    """).fetchall()
    if not rows:
        print("database is empty")
        return
    print(f"{'AUTHOR':20}{'VIEWS':>10}{'SECS':>6}{'CHARS':>7}  {'GPTZERO':12}{'AI PROB':>8}  {'CLASS':11}  ROUTE")
    print("-" * 96)
    for author, views, dur, chars, status, prob, doc_class, sub, route, url in rows:
        p = f"{prob:.2f}" if prob is not None else "-"
        v = f"{views:,}" if views else "-"
        print(f"{('@' + (author or '?'))[:19]:20}{v:>10}{(dur or 0):>6.0f}{(chars or 0):>7}  {(status or '-'):12}{p:>8}  {(doc_class or '-')[:10]:11}  {route or '-'}")
    print("-" * 96)
    total = len(rows)
    with_text = [r for r in rows if r[3]]
    scored = [r for r in rows if r[4] == "scored"]
    waiting = [r for r in rows if r[4] == "skipped" and r[3] and r[3] >= 200]
    print(f"{total} videos in the database, {len(with_text)} with a transcript.")
    if scored:
        flagged = [r for r in scored if (r[5] or 0) >= 0.5]
        print(f"{len(scored)} scored by GPTZero. {len(flagged)}/{len(scored)} "
              f"({100 * len(flagged) / len(scored):.0f}%) read as at least half AI probable.")
    else:
        print("No GPTZero scores yet.")
    if waiting:
        print(f"{len(waiting)} transcripts are long enough and waiting on a GPTZERO_API_KEY. "
              f"Set it and rerun scan_batch.py, already scanned rows are skipped, so rescore with: "
              f"sqlite3 transcripts.db \"UPDATE transcripts SET gptzero_status=NULL WHERE gptzero_status='skipped'\"")
    conn.close()


if __name__ == "__main__":
    main()
