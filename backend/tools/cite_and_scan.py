"""
Glue: whenever the resolver gets full text for a cited paper, also score it for
AI authorship and store the result. This is the "byproduct of normal use" path
the team chose, no separate crawl, the database grows every time a claim pulls
in a new paper.

Usage:
    export GPTZERO_API_KEY=...
    python3 cite_and_scan.py <search-query> [<search-query> ...]

Each query goes through the same Europe PMC search + resolve_fulltext chain
already tested on the blue-light video, and every paper that comes back as
full_text gets GPTZero'd and stored. Papers that only got an abstract are
skipped, not scored badly, per the team's decision to scan full texts only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

from paper_authorship import report, scan_paper, store
from resolver import resolve_fulltext, verify_match

EMAIL = "ezekieljoseph2005@gmail.com"


def search_one(query: str) -> dict | None:
    params = {"query": query, "format": "json", "resultType": "core", "pageSize": 1, "sort": "CITED desc"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": f"HypeCheck/0.1 (mailto:{EMAIL})"})
    results = json.loads(urllib.request.urlopen(req, timeout=25).read())["resultList"]["result"]
    return results[0] if results else None


def main() -> None:
    import os
    api_key = os.environ.get("GPTZERO_API_KEY")
    if not api_key:
        print("GPTZERO_API_KEY is not set. Scans will be recorded as skipped.")

    queries = sys.argv[1:]
    if not queries:
        print(__doc__)
        return

    for query in queries:
        record = search_one(query)
        time.sleep(0.35)
        if not record:
            print(f"[not found] {query}")
            continue
        if not verify_match(record):
            print(f"[match check declined to trust this candidate] {query}")
            continue
        paper_id = record.get("pmcid") or record.get("doi") or record.get("pmid")
        result = resolve_fulltext(record, EMAIL)
        if result["access_type"] != "full_text":
            print(f"[{result['access_type']}, not scanned] {paper_id}  {record.get('title', '')[:60]}")
            continue
        scan = scan_paper(paper_id, result["text"], api_key)
        store(scan)
        print(f"[scanned] {paper_id}  {record.get('title', '')[:60]}  "
              f"status={scan.status}  ai_prob={scan.ai_probability}")

    print()
    report()


if __name__ == "__main__":
    main()
