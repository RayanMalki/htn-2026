"""Read-only live retrieval comparison; never creates cases, indexes or endpoints.

Freeze a candidate pool from the existing index, then compare current RRF with
optional reranking. This isolates ranking, NOT live discovery quality. Annotation
is a separate review step; missing labels are never counted as relevant.
"""
import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic

import httpx

from app.config import settings
from app.models import quotation_catalog
from app.schemas import Verdict, validate_verdict
from app.search import ElasticSearch

QUERIES = {
    "vitamin-c": "Regular vitamin C supplementation prevents common colds in adults.",
    "screen-light": "Blue light rather than screen brightness delays sleep onset in adults.",
    "melatonin": "Melatonin improves sleep onset in adults.",
}


async def run(args):
    cfg = settings()
    if not cfg.elasticsearch_url or not cfg.elasticsearch_api_key:
        raise SystemExit("Configure server-side Elasticsearch credentials first.")
    report = {"scope": "Frozen existing-index candidate pools; ranking only; no discovery or judgment evaluation",
              "runs": []}
    async with httpx.AsyncClient(timeout=20) as client:
        search = ElasticSearch(client)
        for name, query in QUERIES.items():
            # Only benchmark pool construction searches the existing corpus broadly.
            # Production retains its per-claim discovery candidate_ids restriction.
            response = await search.call("POST", f"/{cfg.elastic_index}/_search", json={
                "size": 100, "_source": False, "query": {"bool": {
                    "must": {"multi_match": {"query": query, "fields": ["text", "title^1.5"]}},
                    "filter": [{"term": {"known_retracted": False}}],
                }}})
            ids = [hit["_id"] for hit in response.json()["hits"]["hits"]]
            for variant in ["baseline", "reranked"]:
                cfg.elastic_rerank_enabled = variant == "reranked"
                cfg.elastic_rerank_inference_id = args.endpoint
                metadata = {}
                started = monotonic()
                passages, mode = await search.retrieve(query, ids, diagnostics=metadata)
                citations = list(quotation_catalog(passages).values())[:6]
                validate_verdict(Verdict(label="uncertain", explanation="Benchmark quotation integrity only.",
                                        citations=citations, limitations=[]), passages)
                report["runs"].append({"query_id": name, "query": query, "variant": variant,
                    "seconds": round(monotonic() - started, 4), "mode": mode,
                    "candidate_ids": ids, "reranking": metadata, "passages": [p.model_dump() for p in passages],
                    "unique_papers": len({p.paper_id for p in passages}),
                    "valid_exact_quotes": len(citations), "quote_check": "catalog samples, not model verdict citations"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps([{k: v for k, v in run.items() if k not in {"passages", "candidate_ids"}}
                      for run in report["runs"]], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Existing, permitted rerank endpoint ID")
    parser.add_argument("--output", type=Path, default=Path("artifacts/retrieval-benchmark.json"))
    asyncio.run(run(parser.parse_args()))
