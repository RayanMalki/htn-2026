"""Decide whether a reference exists, without trusting a nearest match.

Crossref answers every query with its closest records, so a hit proves nothing on
its own. The first version of this check accepted any 25 shared characters, and
"Alzheimer's disease classification" is 34. That rule cleared invented references
as real. This one asks for the whole title, plus a second agreeing fact.
"""
import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

CROSSREF = "https://api.crossref.org/works"
TITLE_COVERAGE = 0.85
WINDOW_RATIO = 0.9

# Reference classes Crossref indexes poorly. A miss here means "we cannot check
# this", not "it does not exist". Measured: a real 2001 Oxford University Press
# book chapter came back unresolvable and looked like the first fabrication.
UNCHECKABLE = ("university press", "eds.", "editors", " in ", "chapter",
               "thesis", "dissertation", "978-", "isbn")


def words(text: str) -> list[str]:
    """Lowercase ASCII tokens. Markup and typographic dashes become spaces first:
    Crossref stores "anti\u2010inflammatory" and "<scp>TNF</scp>", and dropping those
    characters instead of splitting on them cost two known-real references."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", " ", text)
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", plain).split()


def window_ratio(title: list[str], cited: list[str]) -> float:
    """Character similarity between the title and the stretch of the citation it
    lines up with. Rescues titles whose letters were damaged in the database
    ("Todeszeitsch?tzungen"). A chimera still fails: half a title scores near 0.5."""
    a, b = " ".join(title), " ".join(cited)
    anchor = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    if anchor.size < 12:
        return 0.0
    start = max(0, anchor.b - anchor.a)
    return SequenceMatcher(None, a, b[start:start + len(a)], autojunk=False).ratio()


def title_agrees(item: dict, citation: str) -> bool:
    """True when the record's whole title sits inside the citation, in order, and
    either an author surname or the year agrees as well."""
    title = words(" ".join(item.get("title") or []))
    cited = words(citation)
    if len(title) < 3 or not cited:
        return False
    blocks = SequenceMatcher(None, title, cited, autojunk=False).get_matching_blocks()
    covered = sum(b.size for b in blocks) / len(title)
    longest = max((b.size for b in blocks), default=0)
    if covered < TITLE_COVERAGE or longest < min(4, len(title)):
        if window_ratio(title, cited) < WINDOW_RATIO:
            return False
    joined = " ".join(cited)
    surnames = [" ".join(words(a.get("family") or "")) for a in (item.get("author") or [])[:4]]
    author_ok = any(s and f" {s} " in f" {joined} " for s in surnames)
    years = set()
    for key in ("issued", "published", "published-print", "published-online"):
        parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            years |= {str(parts[0] + d) for d in (-1, 0, 1)}
    year_ok = any(y in cited for y in years)
    return author_ok or year_ok


def authors_agree(item: dict, citation: str) -> bool | None:
    """Does any listed author appear in the citation? None when the record lists
    no people. A real title under invented names is the commonest machine-made
    citation, and a title match alone waves it through."""
    surnames = [" ".join(words(a.get("family") or "")) for a in (item.get("author") or [])[:8]]
    surnames = [s for s in surnames if s]
    if not surnames:
        return None
    joined = f" {' '.join(words(citation))} "
    return any(f" {s} " in joined for s in surnames)


class Unavailable(RuntimeError):
    """Crossref did not answer. Never the same thing as "not found"."""


_gate = asyncio.Lock()


async def crossref_items(client, citation: str) -> list[dict]:
    """One request at a time, because the public pool allows a single connection.
    A refusal is retried, then raised. Measured: treating a 429 as an empty result
    made 28 of 30 known-real references look missing."""
    probe = " ".join(citation.split())[:240]
    async with _gate:
        for attempt in range(5):
            r = await client.get(CROSSREF, params={"query.bibliographic": probe, "rows": 5,
                                                   "select": "DOI,title,author,issued,published"})
            if r.status_code == 200:
                await asyncio.sleep(0.25)
                return (r.json().get("message") or {}).get("items") or []
            wait = r.headers.get("retry-after", "")
            await asyncio.sleep(float(wait) if wait.isdigit() else 2 * (attempt + 1))
    raise Unavailable(f"Crossref HTTP {r.status_code}")
