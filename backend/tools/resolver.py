"""
Full-text resolver for HypeCheck, the honest way to read more than abstracts.

The backend's literature.py already reads full text for open-access papers that sit
in PubMed Central. This adds the two layers it is missing, both found the hard way
while testing the blue-light video:

  1. A match check. A loose title search can return the wrong paper (we saw a 2001
     claim resolve to a 2021 paper and a veterinary journal). Never trust a candidate
     whose year or first author does not line up.
  2. An Unpaywall step. When a paper is not in the open PubMed Central set, Unpaywall
     finds the legally free copy the publisher or a repository is already hosting. That
     took our coverage on real studies from 1 of 8 to 3 of 8 and up.

Every source here is one a person could open in a browser for free. No login, no
library cookie, no paywall bypass. Papers with no free copy anywhere stay as abstracts
with a badge that says so, because for a meta-analysis the abstract states the result.

Standalone so it runs and is tested outside the backend. It mirrors the shapes in
literature.py (a record dict from Europe PMC, an access_type badge) so porting it in is
mostly moving functions, not rewriting them.
"""

import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "HypeCheck/0.1 (hackathon fact-checker; mailto:{email})"


def _get(url: str, email: str, timeout: float = 25.0):
    """
    One GET with a proper contact header. Returns (bytes, seconds, error).

    An HTTP error still returns whatever body the server sent (many anti-bot walls
    answer 403 with a normal HTML challenge page), and the error string is prefixed
    "HTTP {status}" so a caller can tell a real block (403, 429, 503) apart from a
    connection that never happened at all (refused, timed out, no such host). Losing
    that distinction is what made a live paper and a dead domain look identical.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA.format(email=email)})
    start = time.time()
    try:
        data = urllib.request.urlopen(req, timeout=timeout).read()
        return data, time.time() - start, None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return (body or None), time.time() - start, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - report every failure, never raise into the pipeline
        return None, time.time() - start, str(exc)[:80]


def _is_block_status(err: str | None) -> bool:
    """True when the failure was the server actively refusing us, not a dead host."""
    return bool(err) and err.startswith("HTTP ") and err[5:] in ("403", "429", "503")


def verify_match(record: dict, want_year: int | None = None, want_author: str | None = None) -> bool:
    """
    Guard against the wrong-paper match. A candidate passes only if the year is within
    a year (indexing dates drift) and the wanted author appears in the author list.
    When we have no expectation to check against, the candidate passes.
    """
    if want_year is not None:
        try:
            got = int(str(record.get("pubYear") or 0))
        except ValueError:
            return False
        if abs(got - want_year) > 1:
            return False
    if want_author:
        authors = (record.get("authorString") or "").lower()
        if want_author.lower() not in authors:
            return False
    return True


def _pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from a downloaded PDF using poppler's pdftotext."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(pdf_bytes)
        path = handle.name
    try:
        out = subprocess.run(
            ["pdftotext", "-q", path, "-"],
            capture_output=True,
            timeout=30,
        )
        return out.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        Path(path).unlink(missing_ok=True)


def _bot_blocked(html: bytes) -> bool:
    """Cheap check for a Cloudflare or similar bot-challenge page instead of the article."""
    head = html[:4000].lower()
    return any(marker in head for marker in (b"just a moment", b"checking your browser", b"cf-browser-verification", b"security service to protect against malicious bots", b"ray id:"))


# Journal platforms that migrated domains. Europe PMC's fullTextUrlList still names the
# old host for older papers (West 2011 pointed at intl-jap.physiology.org, which no
# longer resolves at all). Rewrite the host and reshape the path when we know the pattern,
# so a dead legacy link still finds the paper at its current home instead of giving up.
_DOMAIN_MIGRATIONS = [
    # intl-jap.physiology.org/cgi/content/full/{volume}/{issue}/{page} -> journals.physiology.org/doi/full/{doi}
    (re.compile(r"^https?://intl-jap\.physiology\.org/cgi/content/full/"), None),
]


def _candidate_urls(url: str, doi: str | None) -> list[str]:
    """The given URL first, then any known-good replacement for a dead legacy host."""
    candidates = [url]
    if doi and re.match(r"^https?://intl-jap\.physiology\.org/", url):
        candidates.append(f"https://journals.physiology.org/doi/full/{doi}")
    return candidates


def resolve_fulltext(record: dict, email: str, gap: float = 0.35) -> dict:
    """
    Try, in order of quality, to get the real text of a paper. Returns a dict with:
      access_type : "full_text", "free_needs_browser", or "abstract_only"
      route       : which source succeeded
      text        : the text we got (full body or the abstract)
      chars       : its length
      seconds     : total request time spent
      free_url    : set when a free copy exists but a script cannot pull it (see below)

    "free_needs_browser" is its own state, separate from "abstract_only". West 2011 in
    testing is exactly this case: Europe PMC's own fullTextUrlList names a free page,
    a human clicking it gets the paper instantly, but the page sits behind a bot
    challenge that a plain script fetch cannot pass. Calling that "abstract only" would
    be dishonest, since it is not paywalled, so it gets its own badge with the link, and
    the page can show "free full text available, click through" rather than pretending
    the abstract is all there is.

    `gap` is a small pause between requests. Firing them back to back exhausted local
    sockets during testing and crashed the run, which is exactly the failure you do not
    want when three judges trigger at once.
    """
    pmcid = record.get("pmcid")
    doi = record.get("doi")
    spent = 0.0

    # Route 1: Europe PMC full text, for the open PubMed Central subset. Gives clean
    # sectioned XML and, via BioC elsewhere, character offsets for the exact-sentence view.
    if record.get("isOpenAccess") == "Y" and pmcid:
        # Two attempts with a short backoff. In the failure-mode suite this route
        # failed once, transiently, right after a burst of searches. With no retry the
        # paper fell through to a mirror that sits behind a permanent bot wall, and a
        # paper that had been full text all day came back "free_needs_browser". An
        # upstream hiccup costs 1.5 s to absorb. A wrong access badge costs credibility.
        for attempt in range(2):
            data, dt, err = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", email)
            spent += dt
            if data and data[:5] == b"<?xml":
                text = " ".join(re.sub(r"<[^>]+>", " ", data.decode("utf-8", "replace")).split())
                if len(text) > 1500:
                    return {"access_type": "full_text", "route": "europe_pmc_xml", "text": text, "chars": len(text), "seconds": round(spent, 2)}
            if attempt == 0:
                time.sleep(1.5)
        time.sleep(gap)
        # Second official source for the same open subset. No auth, JSON, about 0.2 s
        # all day, and it returns passages with character offsets, which is what the
        # exact-sentence highlight needs anyway. A miss comes back as "[Error]", not
        # as a non-200, so check the body.
        data, dt, err = _get(f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid}/unicode", email)
        spent += dt
        time.sleep(gap)
        if data and data[:2] == b"[{":
            try:
                doc = json.loads(data)[0]["documents"][0]
                text = " ".join(" ".join(p.get("text", "") for p in doc.get("passages", [])).split())
            except (ValueError, KeyError, IndexError, TypeError):
                text = ""
            if len(text) > 1500:
                return {"access_type": "full_text", "route": "ncbi_bioc", "text": text, "chars": len(text), "seconds": round(spent, 2)}

    # Route 2: Europe PMC's OWN list of free full-text links. This is the "click here
    # for free full text" list a human sees on the article page, separate from whether
    # Unpaywall or PMC happen to mirror the same file. West 2011 only turned up here:
    # Unpaywall said is_oa=False, but Europe PMC still names a free HTML copy at the
    # publisher, embargo expired. Try any entry marked Free before trying subscription
    # links, and note when it is bot-gated rather than pretend it does not exist.
    # best_blocked tracks the first free-but-gated link across EVERY entry in the list,
    # not just one. A paper often has several free mirrors (Europe PMC's own copy, the
    # publisher's, a repository's), and one of them being blocked must not stop us from
    # trying the rest for real full text. Only fall back to "free but gated" once every
    # entry has been tried and none gave full text.
    best_blocked = None
    for link in record.get("fullTextUrlList", {}).get("fullTextUrl", []):
        availability = link.get("availability") or ""
        # "Free after 12 months" etc is an embargo note, not a current restriction. The
        # embargo has already passed for anything published more than a year ago, which
        # is every case we ever call this on, so treat any "Free..." label as free now.
        # Do not treat documentStyle "abs" as full text, that link only opens the
        # abstract page even though its availability also reads Free.
        if not availability.startswith(("Free", "Open access")):
            continue
        if link.get("documentStyle") == "abs":
            continue
        url = link.get("url")
        if not url or url.lower().endswith(".pdf"):
            continue
        # Try the URL Europe PMC gave us, then any known replacement if that host is
        # dead. A dead legacy domain (connection refused) is not the same finding as a
        # live page that blocks scripts, and the two should not collapse to one result.
        for candidate in _candidate_urls(url, doi):
            data, dt, err = _get(candidate, email, timeout=20)
            spent += dt
            time.sleep(gap)
            blocked = _is_block_status(err) or (data and _bot_blocked(data))
            if blocked:
                # The server actively refused us (403/429/503) or served a challenge
                # page. Remember it, but keep trying every other link and candidate
                # first, one of them might not be gated at all.
                if best_blocked is None:
                    best_blocked = (candidate, link.get("site"))
                continue
            if not data:
                continue  # a dead host (connection refused, DNS failure, timeout), not a block
            text = " ".join(re.sub(r"<[^>]+>", " ", data.decode("utf-8", "replace")).split())
            if len(text) > 1500:
                return {"access_type": "full_text", "route": f"europe_pmc_link:{link.get('site')}", "text": text, "chars": len(text), "seconds": round(spent, 2)}
    if best_blocked:
        # Say so plainly rather than calling it abstract_only. The paper is free,
        # a person clicking this link gets it, a script fighting the bot check does not.
        free_url, site = best_blocked
        return {"access_type": "free_needs_browser", "route": f"europe_pmc_link:{site}", "free_url": free_url, "text": record.get("abstractText", ""), "chars": 0, "seconds": round(spent, 2)}

    # Route 3: Unpaywall points at the free copy the publisher or a repository hosts.
    if doi:
        clean = doi.replace("https://doi.org/", "").strip()
        data, dt, err = _get(f"https://api.unpaywall.org/v2/{clean}?email={urllib.parse.quote(email)}", email)
        spent += dt
        time.sleep(gap)
        if data:
            try:
                info = json.loads(data)
            except json.JSONDecodeError:
                info = {}
            loc = info.get("best_oa_location") or {}
            if info.get("is_oa") and (loc.get("url_for_pdf") or loc.get("url")):
                pdf_url = loc.get("url_for_pdf")
                if pdf_url:
                    pdf, dt2, err = _get(pdf_url, email, timeout=30)
                    spent += dt2
                    time.sleep(gap)
                    if pdf and pdf[:4] == b"%PDF":
                        text = " ".join(_pdf_to_text(pdf).split())
                        if len(text) > 1500:
                            return {"access_type": "full_text", "route": f"unpaywall_pdf:{loc.get('host_type')}", "text": text, "chars": len(text), "seconds": round(spent, 2)}
                # An HTML free copy: a plain fetch may be a JS shell. Hand the URL to the
                # Playwright renderer (tools/fulltext_render.mjs) which reads it properly.
                html_url = loc.get("url")
                if html_url and not html_url.lower().endswith(".pdf"):
                    return {"access_type": "needs_render", "route": f"unpaywall_html:{loc.get('host_type')}", "render_url": html_url, "text": record.get("abstractText", ""), "chars": 0, "seconds": round(spent, 2)}
            elif info.get("is_oa") is False:
                pass  # genuinely paywalled, fall through to the abstract

    # Route 4: the abstract, badged so the page never pretends it read the whole paper.
    abstract = record.get("abstractText", "") or ""
    return {"access_type": "abstract_only", "route": "abstract", "text": abstract, "chars": len(abstract), "seconds": round(spent, 2)}
