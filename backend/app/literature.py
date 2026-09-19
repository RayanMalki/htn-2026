import asyncio
import hashlib
import re
from datetime import UTC, timedelta

import httpx
from defusedxml import ElementTree

from app.db import PaperCache, now, session
from app.http import request
from app.schemas import Claim, Passage

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


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
        raw = [record for tier in tiers for record in tier]
        unique = {}
        for record in raw:
            types = record.get("pubTypeList", {}).get("pubType", [])
            # References to a retraction are not themselves reliable evidence for a verdict.
            if any("retract" in kind.lower() for kind in types):
                continue
            key = record.get("pmid") or record.get("doi") or f"{record.get('source')}:{record['id']}"
            unique.setdefault(key, record)
        records = list(unique.values())[:15]
        eligible = {r.get("pmcid") for r in records if r.get("isOpenAccess") == "Y" and r.get("pmcid")}
        full_ids = set(sorted(eligible)[:5])
        outcomes = await asyncio.gather(*(self.paper(r, r.get("pmcid") in full_ids) for r in records))
        passages = [p for ps, _, _ in outcomes for p in ps]
        return passages, {
            "query": query, "queries": queries, "provider": "Europe PMC", "searched_at": now().isoformat(),
            "papers_found": len(records), "passages_found": len(passages),
            "cache_hits": sum(c for _, c, _ in outcomes),
            "full_text_fallbacks": sum(f for _, _, f in outcomes),
            "candidate_ids": sorted({p.paper_id for p in passages}),
        }

    async def paper(self, record: dict, fetch_full: bool):
        paper_id = f"{record.get('source', 'MED')}:{record['id']}"
        types = record.get("pubTypeList", {}).get("pubType", [])
        meta = {
            "paper_id": paper_id, "title": plain_text(record.get("title", "Untitled")),
            "source_url": f"https://europepmc.org/article/{record.get('source', 'MED')}/{record['id']}",
            "published": record.get("firstPublicationDate"), "study_types": types,
            "access_type": "abstract_only", "known_retracted": False,
        }
        with session() as db:
            cached = db.get(PaperCache, paper_id)
            if cached and cached.fetched_at.replace(tzinfo=UTC) > now() - timedelta(hours=24):
                saved = [Passage.model_validate(p) for p in cached.data["passages"]]
                if saved and (not fetch_full or saved[0].access_type == "full_text"):
                    # Refresh study metadata from the current discovery response, including retractions.
                    return [p.model_copy(update={"study_types": types}) for p in saved], 1, 0
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
