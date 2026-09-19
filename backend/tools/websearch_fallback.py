"""
Web-search evidence fallback for HypeCheck.

When it fires: only when the literature search came back thin. Fewer than two
usable studies (a usable study takes a side, supports or contradicts), or every
study found is unclear. When real papers exist this is never called. The guard
is in the function, not in a comment: search_and_write returns None unless
should_fallback says the evidence is thin.

What it does: asks OpenAI's Responses application programming interface (API),
with the built-in web_search tool restricted to an allowlist of guideline and
public-health domains, to gather sources and write a short credibility paragraph
with numbered citations. This is the "clinical guidelines and public-health
sources" node from the research design, and it spends the team's OpenAI credits.

How it is badged: every result carries source_badge "web_sources" and a plain
badge_text so the page can say "from guidelines and public-health sources, not
the primary literature". Same honesty rule as the resolver's access badges. It
never produces a numeric score. The verdict in this project is information.

Request shape, confirmed from the docs on 2026-09-19 at
https://developers.openai.com/api/docs/guides/tools-web-search
    POST https://api.openai.com/v1/responses
    tools: [{"type": "web_search",
             "search_context_size": "low|medium|high",
             "filters": {"allowed_domains": [...]}}]
    output items: "web_search_call" (with action.queries), then "message" whose
    content[0] is {"type": "output_text", "text": ..., "annotations": [
        {"type": "url_citation", "url", "title", "start_index", "end_index"}]}

Mock mode: with no OPENAI_API_KEY the function returns a canned response in the
exact same shape, so the pipeline and the page can be built without spending.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

# The cheaper current text model, confirmed on the models page 2026-09-19:
# gpt-5.6-terra is 2 dollars in and 12 out per million tokens and supports the
# web_search tool. The flagship gpt-6-astra is 10 and 50, five times the price,
# and a cited paragraph does not need it. gpt-5.6-luna (0.20 and 1.20) is the
# budget option if credits run low, swap the constant.
MODEL = "gpt-5.6-terra"
PRICE_PER_MILLION = {"input": 2.0, "output": 12.0}

ENDPOINT = "https://api.openai.com/v1/responses"
TIMEOUT_SECONDS = 45

# Only guideline and public-health publishers. The search tool is told to stay
# inside these, and parse_response drops anything outside them as well, in case
# a result slips through.
ALLOWED_DOMAINS = [
    "who.int", "cdc.gov", "nih.gov", "nlm.nih.gov", "nhs.uk", "canada.ca",
    "cochrane.org", "mayoclinic.org", "health.harvard.edu", "fda.gov", "ema.europa.eu",
]

PUBLISHERS = {
    "who.int": "World Health Organization", "cdc.gov": "Centers for Disease Control and Prevention",
    "nih.gov": "National Institutes of Health", "nlm.nih.gov": "National Library of Medicine",
    "nhs.uk": "National Health Service", "canada.ca": "Government of Canada",
    "cochrane.org": "Cochrane", "mayoclinic.org": "Mayo Clinic",
    "health.harvard.edu": "Harvard Health", "fda.gov": "Food and Drug Administration",
    "ema.europa.eu": "European Medicines Agency",
}

MIN_USABLE_STUDIES = 2
STANCES = ("supports", "contradicts", "unclear", "insufficient")
# The team backend spells the middle state "uncertain". Treat it as unclear here.
UNCLEAR_WORDS = {"unclear", "uncertain", "mixed", "neutral"}
SOURCE_BADGE = "web_sources"
BADGE_TEXT = "From guidelines and public-health sources, not the primary literature"


def should_fallback(evidence_summary) -> bool:
    """
    True when the literature is too thin to judge from. evidence_summary is a
    list of study dicts each carrying a "stance", or a dict with a "studies" list.
    Fires on fewer than MIN_USABLE_STUDIES studies that take a side, and on a
    set where every study is unclear. Two clear studies means no fallback.
    """
    studies = evidence_summary.get("studies", []) if isinstance(evidence_summary, dict) else list(evidence_summary or [])
    stances = [str(s.get("stance", "")).lower() for s in studies if isinstance(s, dict)]
    usable = [s for s in stances if s in ("supports", "contradicts")]
    if len(usable) < MIN_USABLE_STUDIES:
        return True
    return all(s in UNCLEAR_WORDS for s in stances)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _allowed(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def _publisher(url: str) -> str:
    host = _host(url)
    for domain, name in PUBLISHERS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def _instructions(claim: str, evidence_summary) -> str:
    studies = evidence_summary.get("studies", []) if isinstance(evidence_summary, dict) else list(evidence_summary or [])
    return (
        "You are the fallback step of a health fact-checker. The peer-reviewed literature "
        f"search for this claim returned only {len(studies)} usable studies, so you must "
        "check it against clinical guidelines and public-health sources instead. Search only "
        "the domains you are given. Then answer with a single JSON object and nothing else, "
        "with exactly these keys: "
        '"stance" (one of supports, contradicts, unclear, insufficient), '
        '"paragraph" (2 to 4 plain sentences on how credible the claim is, with inline numbered '
        'citations like [1] that match the citations list), '
        '"citations" (a list of objects with keys url, title, publisher, quote, where quote is '
        "the exact sentence from the source you relied on), "
        '"confidence_note" (one sentence on how strong these sources are and what is missing). '
        "Never give a number out of 5 or 10 or a percentage as a score. Do not invent sources. "
        "If the credible sources say nothing usable, set stance to insufficient and say so.\n\n"
        f"Claim: {claim}"
    )


def _request_body(claim: str, evidence_summary) -> dict:
    """The exact shape the docs specify. Kept in one place so the test can assert it."""
    return {
        "model": MODEL,
        "input": _instructions(claim, evidence_summary),
        "tools": [{
            "type": "web_search",
            "search_context_size": "medium",
            "filters": {"allowed_domains": ALLOWED_DOMAINS},
        }],
        "include": ["web_search_call.action.sources"],
    }


def _extract_json(text: str) -> dict:
    """The model is told to return one JSON object. Tolerate stray prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def parse_response(body: dict, mode: str = "live") -> dict:
    """
    Turn a Responses API body into the fallback result shape. Reads the message
    item's output_text, parses the JSON the model was asked for, and folds in any
    url_citation annotations the tool attached. Citations outside the allowlist
    are dropped. Any numeric score the model slips in is removed.
    """
    text = ""
    annotations = []
    queries = []
    for item in body.get("output", []) or []:
        if item.get("type") == "web_search_call":
            queries.extend((item.get("action") or {}).get("queries") or [])
        if item.get("type") == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    text += part.get("text", "")
                    annotations.extend(a for a in (part.get("annotations") or []) if a.get("type") == "url_citation")

    model_json = _extract_json(text)
    for key in ("score", "rating", "confidence_score"):
        model_json.pop(key, None)

    citations = []
    seen = set()
    for c in model_json.get("citations", []) or []:
        url = str(c.get("url", "")).strip()
        if url and _allowed(url) and url not in seen:
            seen.add(url)
            citations.append({
                "url": url, "title": str(c.get("title", "")).strip()[:200],
                "publisher": str(c.get("publisher") or _publisher(url))[:100],
                "quote": str(c.get("quote", "")).strip()[:600],
            })
    for a in annotations:
        url = str(a.get("url", "")).strip()
        if url and _allowed(url) and url not in seen:
            seen.add(url)
            citations.append({"url": url, "title": str(a.get("title", ""))[:200], "publisher": _publisher(url), "quote": ""})

    stance = str(model_json.get("stance", "")).lower()
    if stance in UNCLEAR_WORDS:
        stance = "unclear"
    if stance not in STANCES:
        stance = "insufficient" if not citations else "unclear"

    usage = body.get("usage") or {}
    cost = None
    if usage:
        cost = round((usage.get("input_tokens", 0) * PRICE_PER_MILLION["input"]
                      + usage.get("output_tokens", 0) * PRICE_PER_MILLION["output"]) / 1_000_000, 5)

    return {
        "source_badge": SOURCE_BADGE,
        "badge_text": BADGE_TEXT,
        "stance": stance,
        "paragraph": str(model_json.get("paragraph", "")).strip(),
        "citations": citations,
        "confidence_note": str(model_json.get("confidence_note", "")).strip(),
        "queries": queries,
        "model": body.get("model", MODEL),
        "mode": mode,
        "usage": usage,
        "estimated_cost_usd": cost,
    }


def _mock(claim: str) -> dict:
    """Same shape as a live result, so the page and pipeline build without a key."""
    return {
        "source_badge": SOURCE_BADGE,
        "badge_text": BADGE_TEXT,
        "stance": "contradicts",
        "paragraph": (
            "Public-health sources do not support the idea that alkaline water prevents or treats "
            "cancer [1]. The body keeps blood pH in a narrow range regardless of what is eaten or "
            "drunk, so drinking alkaline water does not make the body alkaline [2]. Cancer agencies "
            "list this among claims with no supporting evidence in people [1]."
        ),
        "citations": [
            {"url": "https://www.cdc.gov/cancer/", "title": "Cancer basics",
             "publisher": "Centers for Disease Control and Prevention",
             "quote": "There is no evidence that alkaline water prevents or treats cancer."},
            {"url": "https://www.nhs.uk/conditions/", "title": "Diet and cancer",
             "publisher": "National Health Service",
             "quote": "Your body tightly controls the pH of your blood, and diet cannot change it."},
        ],
        "confidence_note": "Mock response, no search was run. Two public-health pages, no trial data.",
        "queries": [f"{claim} guideline", f"{claim} public health"],
        "model": MODEL,
        "mode": "mock",
        "usage": {},
        "estimated_cost_usd": 0.0,
    }


def search_and_write(claim: str, evidence_summary, api_key: str | None = None) -> dict | None:
    """
    The fallback. Returns None when the literature was sufficient, which is the
    guard the design calls for. Otherwise returns the result shape from
    parse_response, in mock mode when there is no key.
    """
    if not should_fallback(evidence_summary):
        return None
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _mock(claim)

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(_request_body(claim, evidence_summary)).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {**_mock(claim), "mode": "error", "stance": "insufficient",
                "paragraph": "", "citations": [], "confidence_note": f"Web search failed: HTTP {exc.code} {detail}"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {**_mock(claim), "mode": "error", "stance": "insufficient",
                "paragraph": "", "citations": [], "confidence_note": f"Web search failed: {str(exc)[:200]}"}
    return parse_response(body, mode="live")


if __name__ == "__main__":
    import sys
    claim = " ".join(sys.argv[1:]) or "Alkaline water prevents or treats cancer"
    result = search_and_write(claim, [], os.environ.get("OPENAI_API_KEY"))
    print(json.dumps(result, indent=2))
