import asyncio
import hashlib
import re
from datetime import UTC, timedelta
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree

from app.config import settings
from app.db import PaperCache, now, session
from app.http import request
from app.schemas import Claim, Passage

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MEDLINEPLUS_BASE = "https://wsearch.nlm.nih.gov/ws/query"


def plain_text(value: str) -> str:
    try:
        return " ".join("".join(ElementTree.fromstring(f"<root>{value}</root>").itertext()).split())
    except Exception:
        return " ".join(re.sub(r"<[^>]*>", " ", value).split())


def build_query(terms: list[str]) -> str:
    # Models only supply words, never raw query syntax. Search neutral topic terms.
    phrases = []
    for term in terms[:3]:
        directional = {"prevent", "prevents", "prevention", "preventing", "cure", "cures", "cause", "causes", "causing", "improves", "improve", "treat", "treats", "treating"}
        tokens = [word for word in re.findall(r"[A-Za-z0-9]+", term)[:15] if word.lower() not in directional]
        if tokens:
            topic = " AND ".join(f'"{word}"' for word in tokens)
            phrases.append(f"(TITLE_ABS:({topic}))")
    return "(" + " OR ".join(phrases) + ") NOT PUB_TYPE:\"Retracted Publication\""


def chunks(paper: dict, sections: list[tuple[str, str]]) -> list[Passage]:
    result = []
    for section, raw in sections:
        context = plain_text(raw)
        if len(context) < 40:
            continue
        # Paragraph-scoped source text; offsets address this immutable stored context.
        start = 0
        while start < len(context):
            end = min(start + 1400, len(context))
            if end < len(context):
                boundary = context.rfind(". ", start + 400, end)
                if boundary != -1:
                    end = boundary + 1
            text = context[start:end]
            passage_id = hashlib.sha256(f"{paper['paper_id']}|{section}|{context}|{start}".encode()).hexdigest()
            result.append(Passage(id=passage_id, section=section, text=text, context=context,
                                  start=start, end=end, **paper))
            start = end
            while start < len(context) and context[start].isspace():
                start += 1
    return result


class Literature:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.limiter = asyncio.Semaphore(5)

    async def discover(self, claim: Claim) -> tuple[list[Passage], dict]:
        providers = [self._europe_pmc(claim)]
        provider_names = ["Europe PMC"]
        if settings().medlineplus_enabled:
            providers.append(self._medlineplus(claim))
            provider_names.append("MedlinePlus")
        results = await asyncio.gather(*providers, return_exceptions=True)
        passages = []
        provenance = []
        failures = []
        for name, result in zip(provider_names, results, strict=True):
            if isinstance(result, BaseException):
                failures.append({"provider": name, "error": type(result).__name__})
            else:
                found, details = result
                passages.extend(found)
                provenance.append(details)
        if not provenance:
            raise results[0]
        europe = next((item for item in provenance if item["provider"] == "Europe PMC"), None)
        primary = europe or provenance[0]
        return passages, {
            **primary,
            "provider": " + ".join(item["provider"] for item in provenance),
            "providers": provenance,
            "provider_failures": failures,
            "sources_found": sum(item["sources_found"] for item in provenance),
            "passages_found": len(passages),
            "candidate_ids": sorted({p.id for p in passages}),
            "candidate_paper_ids": sorted({p.paper_id for p in passages}),
        }

    async def _europe_pmc(self, claim: Claim) -> tuple[list[Passage], dict]:
        query = build_query(claim.search_terms)
        title_query = query.replace("TITLE_ABS:", "TITLE:")
        review_query = f'({query}) AND (PUB_TYPE:"Systematic Review" OR PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Randomized Controlled Trial")'
        queries = [title_query, review_query, query]

        async def find(expression):
            async with self.limiter:
                response = await request(self.client, "GET", f"{BASE}/search", params={
                    "query": expression + " sort_cited:y", "format": "json", "resultType": "core", "pageSize": 15,
                })
            return response.json().get("resultList", {}).get("result", [])

        tiers = await asyncio.gather(*(find(expression) for expression in queries))
        unique = {}

        def add(record, tier):
            types = record.get("pubTypeList", {}).get("pubType", [])
            if any("retract" in kind.lower() for kind in types):
                return
            key = record.get("pmid") or record.get("doi") or f"{record.get('source')}:{record['id']}"
            if key not in unique:
                unique[key] = {**record, "_discovery_tier": tier}

        # Reserve space for exact-title, strong-study-design, and broad discovery results.
        for tier_number, tier in enumerate(tiers):
            for record in tier[:5]:
                add(record, tier_number)
        for tier_number, tier in enumerate(tiers):
            for record in tier:
                if len(unique) == 15:
                    break
                add(record, tier_number)
        records = list(unique.values())[:15]

        def full_text_priority(record):
            kinds = " ".join(record.get("pubTypeList", {}).get("pubType", [])).lower()
            design = 4 if "systematic review" in kinds or "meta-analysis" in kinds else 3 if "randomized" in kinds else 1
            return (design, -record.get("_discovery_tier", 2), int(record.get("citedByCount") or 0))

        eligible = [r for r in records if r.get("isOpenAccess") == "Y" and r.get("pmcid")]
        full_ids = {r["pmcid"] for r in sorted(eligible, key=full_text_priority, reverse=True)[:5]}
        outcomes = await asyncio.gather(*(self.paper(r, r.get("pmcid") in full_ids) for r in records))
        passages = [p for ps, _, _ in outcomes for p in ps]
        return passages, {
            "query": query, "queries": queries, "provider": "Europe PMC", "searched_at": now().isoformat(),
            "papers_found": len(records), "passages_found": len(passages),
            "sources_found": len(records),
            "cache_hits": sum(c for _, c, _ in outcomes),
            "full_text_fallbacks": sum(f for _, _, f in outcomes),
            "candidate_ids": sorted({p.id for p in passages}),
            "candidate_paper_ids": sorted({p.paper_id for p in passages}),
        }

    async def _medlineplus(self, claim: Claim) -> tuple[list[Passage], dict]:
        term = " ".join(claim.search_terms)
        async with self.limiter:
            response = await request(self.client, "GET", MEDLINEPLUS_BASE, params={
                "db": "healthTopics", "term": term, "retmax": 5,
            })
        root = ElementTree.fromstring(response.content)
        passages = []
        seen = set()
        retrieved = now().isoformat()
        for document in root.findall(".//document"):
            url = document.get("url", "")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in {"medlineplus.gov", "www.medlineplus.gov"}:
                continue
            fields = {}
            for content in document.findall("content"):
                fields[content.get("name", "")] = plain_text(" ".join(content.itertext()))
            summary = fields.get("FullSummary") or fields.get("snippet") or ""
            title = fields.get("title") or "MedlinePlus health topic"
            if len(summary) < 40 or url in seen:
                continue
            seen.add(url)
            external_id = hashlib.sha256(url.encode()).hexdigest()[:20]
            meta = {
                "paper_id": f"MEDLINEPLUS:{external_id}", "title": title, "source_url": url,
                "provider": "medlineplus", "external_id": external_id, "source_kind": "health_topic",
                "published": None, "study_types": ["Curated health topic"], "access_type": "summary",
                "license": None, "retrieved_at": retrieved, "updated_at": None, "known_retracted": False,
            }
            passages.extend(chunks(meta, [("Health topic summary", summary)]))
        return passages, {
            "query": term, "queries": [term], "provider": "MedlinePlus", "searched_at": retrieved,
            "papers_found": 0, "sources_found": len(seen), "passages_found": len(passages),
            "cache_hits": 0, "full_text_fallbacks": 0,
            "candidate_ids": sorted({p.id for p in passages}),
            "candidate_paper_ids": sorted({p.paper_id for p in passages}),
        }

    async def paper(self, record: dict, fetch_full: bool):
        paper_id = f"{record.get('source', 'MED')}:{record['id']}"
        types = record.get("pubTypeList", {}).get("pubType", [])
        meta = {
            "paper_id": paper_id, "title": plain_text(record.get("title", "Untitled")),
            "source_url": f"https://europepmc.org/article/{record.get('source', 'MED')}/{record['id']}",
            "provider": "europe_pmc", "external_id": record.get("pmcid") or record.get("pmid") or record.get("doi"),
            "source_kind": "research_paper", "license": None, "retrieved_at": now().isoformat(),
            "updated_at": None,
            "published": record.get("firstPublicationDate"), "study_types": types,
            "access_type": "abstract_only", "known_retracted": False,
        }
        with session() as db:
            cached = db.get(PaperCache, paper_id)
            if cached and cached.fetched_at.replace(tzinfo=UTC) > now() - timedelta(hours=24):
                saved = [Passage.model_validate(p) for p in cached.data["passages"]]
                if saved and (not fetch_full or saved[0].access_type == "full_text"):
                    # Refresh study metadata from the current discovery response, including retractions.
                    refreshed = {key: value for key, value in meta.items() if key not in {"access_type"}}
                    return [p.model_copy(update=refreshed) for p in saved], 1, 0
        sections = [("Abstract", record.get("abstractText", ""))]
        fallback = 0
        if fetch_full:
            try:
                async with self.limiter:
                    response = await request(self.client, "GET", f"{BASE}/{record['pmcid']}/fullTextXML")
                root = ElementTree.fromstring(response.content)
                body = root.find(".//body")
                full = []
                if body is not None:
                    for sec in body.iter("sec"):
                        title = sec.find("title")
                        label = " ".join(title.itertext()) if title is not None else "Body"
                        full.extend((label, " ".join(p.itertext())) for p in sec.findall("p"))
                    full.extend(("Body", " ".join(p.itertext())) for p in body.findall("p"))
                if full:
                    sections = full
                    meta["access_type"] = "full_text"
                else:
                    fallback = 1
            except (httpx.HTTPError, ElementTree.ParseError, ValueError):
                fallback = 1
        passages = chunks(meta, sections)
        # Concurrent cases may discover the same paper; merge under a savepoint handles the race.
        from sqlalchemy.exc import IntegrityError
        try:
            with session() as db, db.begin():
                db.merge(PaperCache(id=paper_id, fetched_at=now(), data={
                    "passages": [p.model_dump() for p in passages],
                }))
        except IntegrityError:
            pass
        return passages, 0, fallback
