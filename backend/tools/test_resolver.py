"""
Test the resolver on the eight studies the creator himself put on screen in the
blue-light video. Prints, for each: whether the match verified, what route got the
text, full-text or abstract, and how long it took. Ends with the honest coverage number.

Run: python3 test_resolver.py
"""

import json
import time
import urllib.parse
import urllib.request

from resolver import resolve_fulltext, verify_match

EMAIL = "ezekieljoseph2005@gmail.com"

# label, search query, expected year, expected first author (for the match check)
STUDIES = [
    ("Brainard 2001", 'AUTH:"Brainard" AND TITLE:"action spectrum" AND TITLE:"melatonin"', 2001, "Brainard"),
    ("Thapan 2001", 'AUTH:"Thapan" AND TITLE:"action spectrum" AND TITLE:"melatonin"', 2001, "Thapan"),
    ("Figueiro 2011", 'AUTH:"Figueiro" AND TITLE:"computer monitors" AND TITLE:"melatonin"', 2011, "Figueiro"),
    ("Chinoy 2018", 'AUTH:"Chinoy" AND TITLE:"tablet" AND TITLE:"circadian"', 2018, "Chinoy"),
    ("Wood 2013", 'AUTH:"Wood" AND TITLE:"self-luminous" AND TITLE:"melatonin"', 2013, "Wood"),
    ("Cajochen 2011", 'AUTH:"Cajochen" AND TITLE:"light-emitting" AND TITLE:"cognitive"', 2011, "Cajochen"),
    ("Gooley 2010", 'AUTH:"Gooley" AND TITLE:"room light" AND TITLE:"melatonin"', 2010, "Gooley"),
    ("West 2011", 'AUTH:"West" AND TITLE:"dose-dependent" AND TITLE:"melatonin"', 2011, "West"),
]


def search_one(query: str) -> dict | None:
    params = {"query": query, "format": "json", "resultType": "core", "pageSize": 1, "sort": "CITED desc"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": f"HypeCheck/0.1 (mailto:{EMAIL})"})
    data = urllib.request.urlopen(req, timeout=25).read()
    results = json.loads(data)["resultList"]["result"]
    return results[0] if results else None


def main() -> None:
    print(f"{'STUDY':16}{'MATCH':7}{'ACCESS':19}{'ROUTE':26}{'CHARS':>8}  SECS")
    print("-" * 90)
    full = 0
    abstract = 0
    free_blocked = 0
    for label, query, year, author in STUDIES:
        record = search_one(query)
        time.sleep(0.35)
        if not record:
            print(f"{label:16}{'-':7}{'not found':13}")
            continue
        ok = verify_match(record, want_year=year, want_author=author)
        if not ok:
            # the wrong-paper guard fired: we found something, but it is not this study
            print(f"{label:16}{'NO':7}{'rejected':13}{'wrong year/author':26}{'':>8}  (guard worked)")
            continue
        result = resolve_fulltext(record, EMAIL)
        access = result["access_type"]
        if access == "full_text":
            full += 1
        elif access == "needs_render":
            full += 1  # a free HTML copy the renderer will read
        elif access == "free_needs_browser":
            free_blocked += 1  # free, but a script cannot pull it, only a person can click through
        else:
            abstract += 1
        extra = result.get("free_url", "")
        print(f"{label:16}{'yes':7}{access:19}{result['route'][:25]:26}{result['chars']:>8}  {result['seconds']}  {extra}")
    print("-" * 90)
    print(f"Full text reachable (incl. render): {full}/8")
    print(f"Free but bot-blocked (a human can open it, a script cannot): {free_blocked}/8")
    print(f"Genuinely paywalled, abstract only: {abstract}/8")
    print("Compare: the open-access check alone got 1/8 full text and missed the bot-blocked free link entirely.")


if __name__ == "__main__":
    main()
