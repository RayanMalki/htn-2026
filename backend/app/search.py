import asyncio
import json
import math
from time import monotonic
from urllib.parse import quote

import httpx
import sentry_sdk

from app.config import settings
from app.http import request
from app.schemas import Passage


def diversify(passages: list[Passage], limit: int = 6) -> list[Passage]:
    counts: dict[str, int] = {}
    selected = []
    for p in passages:
        if p.known_retracted or counts.get(p.paper_id, 0) >= 2:
            continue
        counts[p.paper_id] = counts.get(p.paper_id, 0) + 1
        selected.append(p)
        if len(selected) == limit:
            break
    return selected


class ElasticSearch:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.cfg = settings()
        self.base = self.cfg.elasticsearch_url.rstrip("/")
        self.headers = {"Authorization": f"ApiKey {self.cfg.elasticsearch_api_key}"}

    async def call(self, method: str, path: str, **kwargs):
        if not self.base or not self.cfg.elasticsearch_api_key:
            raise RuntimeError("Elasticsearch is not configured")
        return await request(self.client, method, self.base + path, headers={**self.headers, "Content-Type": "application/x-ndjson" if "_bulk" in path else "application/json"}, **kwargs)

    async def provision(self):
        properties = {
            "paper_id": {"type": "keyword"}, "title": {"type": "text"},
            "text": {"type": "text", "analyzer": "english"},
            "section": {"type": "keyword"}, "access_type": {"type": "keyword"},
            "provider": {"type": "keyword"}, "external_id": {"type": "keyword"},
            "source_kind": {"type": "keyword"}, "license": {"type": "keyword"},
            "published": {"type": "date", "ignore_malformed": True},
            "updated_at": {"type": "date", "ignore_malformed": True},
            "retrieved_at": {"type": "date", "ignore_malformed": True},
            "study_types": {"type": "keyword"},
            "known_retracted": {"type": "boolean"}, "id": {"type": "keyword"},
            "context": {"type": "text", "index": False},
        }
        if self.cfg.elastic_semantic:
            await self.call("GET", f"/_inference/{self.cfg.elastic_inference_id}")
            properties["semantic"] = {"type": "semantic_text", "inference_id": self.cfg.elastic_inference_id}
        try:
            await self.call("PUT", f"/{self.cfg.elastic_index}", json={
                "mappings": {"properties": properties},
            })
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400 or "resource_already_exists_exception" not in exc.response.text:
                raise
        # Detect an incompatible existing index instead of silently claiming hybrid support.
        mapping = (await self.call("GET", f"/{self.cfg.elastic_index}/_mapping")).json()
        props = next(iter(mapping.values()))["mappings"].get("properties", {})
        if self.cfg.elastic_semantic and props.get("semantic", {}).get("inference_id") != self.cfg.elastic_inference_id:
            raise RuntimeError("Existing index does not match semantic configuration; use a new ELASTIC_INDEX")
        expected_types = {name: definition["type"] for name, definition in properties.items()}
        incompatible = [name for name, expected in expected_types.items()
                        if name in props and props[name].get("type") != expected]
        if incompatible:
            raise RuntimeError(
                f"Existing index has incompatible mappings for {', '.join(incompatible)}; use a new ELASTIC_INDEX")
        missing = {name: definition for name, definition in properties.items() if name not in props}
        if missing:
            await self.call("PUT", f"/{self.cfg.elastic_index}/_mapping", json={"properties": missing})

    async def index(self, passages: list[Passage]) -> dict:
        if not passages:
            return {"index_cache_hits": 0, "indexed": 0, "index_mode": "hybrid"}
        unique = {p.id: p for p in passages}
        current = (await self.call("POST", f"/{self.cfg.elastic_index}/_mget",
            params={"_source_includes": "semantic,study_types,known_retracted,provider,source_kind,access_type"},
            json={"ids": list(unique)},
        )).json()
        existing = {d["_id"]: d.get("_source", {}) for d in current["docs"] if d.get("found")}
        pending = [p for p in unique.values() if p.id not in existing
                   or existing[p.id].get("study_types") != p.study_types
                   or existing[p.id].get("provider") != p.provider
                   or existing[p.id].get("source_kind") != p.source_kind
                   or existing[p.id].get("access_type") != p.access_type
                   or existing[p.id].get("known_retracted") != p.known_retracted
                   or (self.cfg.elastic_semantic and "semantic" not in existing[p.id])]
        semantic = self.cfg.elastic_semantic

        async def bulk(items, use_semantic):
            lines = []
            for passage in items:
                data = passage.model_dump()
                if use_semantic:
                    data["semantic"] = passage.text
                lines.extend([json.dumps({"index": {"_id": passage.id}}), json.dumps(data)])
            if not lines:
                return []
            reply = (await self.call("POST", f"/{self.cfg.elastic_index}/_bulk?refresh=wait_for",
                                     content="\n".join(lines) + "\n",
                                     # Authorization header remains on call; content-type is accepted by HTTPX.
                                     )).json()
            return [item["index"] for item in reply["items"] if item["index"].get("error")]

        failures = await bulk(pending, semantic)
        if failures and semantic:
            sentry_sdk.capture_message("Elastic semantic indexing degraded to keyword", level="warning")
            failed_ids = {f["_id"] for f in failures}
            failures = await bulk([p for p in pending if p.id in failed_ids], False)
            semantic = False
        if failures:
            raise RuntimeError("Elasticsearch bulk indexing failed")
        return {"index_cache_hits": len(unique) - len(pending), "indexed": len(pending),
                "index_mode": "hybrid" if semantic else "keyword_only"}

    def query(self, query: str, candidate_ids: list[str], hybrid: bool):
        filters = [{"ids": {"values": candidate_ids}}, {"term": {"known_retracted": False}}]
        lexical = {"bool": {"must": {"multi_match": {
            "query": query, "fields": ["text", "title^1.5"],
        }}, "filter": filters}}
        base = {"size": 30, "_source": {"excludes": ["semantic"]}}
        if hybrid:
            return {**base, "retriever": {"rrf": {
                "retrievers": [
                    {"standard": {"query": lexical}},
                    {"standard": {"query": {"bool": {
                        "must": {"semantic": {"field": "semantic", "query": query}}, "filter": filters,
                    }}}},
                ], "rank_window_size": 50, "rank_constant": 60,
            }}}
        return {**base, "query": lexical}

    async def rerank(self, query: str, passages: list[Passage], diagnostics: dict):
        diagnostics.clear()
        diagnostics.update(status="disabled")
        if not self.cfg.elastic_rerank_enabled:
            return passages
        endpoint = self.cfg.elastic_rerank_inference_id
        if not endpoint:
            diagnostics.update(status="fallback", reason="endpoint_not_configured")
            return passages
        started = monotonic()
        try:
            async with asyncio.timeout(self.cfg.elastic_rerank_timeout_seconds):
                # Do not create endpoints or retry inference beyond the bounded budget.
                response = await self.client.post(
                    self.base + "/_inference/rerank/" + quote(endpoint, safe=""),
                    headers=self.headers, json={"query": query,
                        "input": [p.title + "\n" + p.text for p in passages[:20]]},
                    timeout=self.cfg.elastic_rerank_timeout_seconds)
                response.raise_for_status()
                ranked = response.json()["rerank"]
                indices = [row["index"] for row in ranked]
                if (len(indices) != min(20, len(passages)) or
                        any(type(i) is not int for i in indices) or
                        set(indices) != set(range(min(20, len(passages)))) or
                        any(not math.isfinite(float(row["relevance_score"])) for row in ranked)):
                    raise ValueError("Invalid rerank result")
                ordered = sorted(ranked, key=lambda row: float(row["relevance_score"]), reverse=True)
                diagnostics.update(status="applied", endpoint=endpoint, shortlist=len(indices))
                return [passages[row["index"]] for row in ordered]
        except (TimeoutError, httpx.TimeoutException):
            diagnostics.update(status="fallback", reason="timeout")
        except httpx.HTTPStatusError as exc:
            diagnostics.update(status="fallback", reason=f"http_{exc.response.status_code}")
        except (httpx.RequestError, ValueError, KeyError, TypeError):
            diagnostics.update(status="fallback", reason="unavailable_or_invalid_response")
        finally:
            diagnostics["seconds"] = round(monotonic() - started, 4)
        return passages

    async def retrieve(self, query: str, candidate_ids: list[str], hybrid: bool | None = None,
                       *, diagnostics: dict | None = None):
        hybrid = self.cfg.elastic_semantic if hybrid is None else hybrid
        if diagnostics is not None:
            diagnostics.update(status="not_needed", reason="no_eligible_passages")
        if not candidate_ids:
            return [], "hybrid" if hybrid else "keyword_only"
        try:
            reply = await self.call("POST", f"/{self.cfg.elastic_index}/_search",
                                    json=self.query(query, candidate_ids, hybrid))
        except httpx.HTTPStatusError as exc:
            if not hybrid or exc.response.status_code not in {400, 402, 403, 429, 500, 503}:
                raise
            sentry_sdk.capture_message("Elastic hybrid retrieval degraded to keyword", level="warning")
            reply = await self.call("POST", f"/{self.cfg.elastic_index}/_search",
                                    json=self.query(query, candidate_ids, False))
            hybrid = False
        allowed = set(candidate_ids)
        passages = [Passage.model_validate(h["_source"]) for h in reply.json()["hits"]["hits"]]
        passages = list({p.id: p for p in passages if p.id in allowed and not p.known_retracted}.values())
        if passages:
            passages = await self.rerank(query, passages, diagnostics if diagnostics is not None else {})
        return diversify(passages), "hybrid" if hybrid else "keyword_only"
