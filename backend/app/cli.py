import argparse
import asyncio
import json
from pathlib import Path

import httpx

from app.config import settings
from app.db import init_db
from app.literature import Literature
from app.schemas import Claim
from app.search import ElasticSearch


async def preflight():
    cfg = settings()
    result = {"model_mode": cfg.model_mode, "sentry_configured": bool(cfg.sentry_dsn), "checks": {}}
    from sqlalchemy import text

    from app.db import session
    from app.queue import redis_client
    for name, check in {
        "database": lambda: _db_check(session, text), "redis": redis_client().ping,
    }.items():
        try:
            check()
            result["checks"][name] = "ok"
        except Exception as exc:
            result["checks"][name] = type(exc).__name__
    async with httpx.AsyncClient(timeout=15) as client:
        search = ElasticSearch(client)
        for name, path in {"elastic_index": f"/{cfg.elastic_index}/_mapping", **(
            {"elastic_inference": f"/_inference/{cfg.elastic_inference_id}"} if cfg.elastic_semantic else {}
        )}.items():
            try:
                await search.call("GET", path)
                result["checks"][name] = "ok"
            except Exception as exc:
                result["checks"][name] = type(exc).__name__
        if cfg.model_mode == "live":
            try:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}",
                    headers={"x-goog-api-key": cfg.gemini_api_key},
                )
                response.raise_for_status()
                result["checks"]["gemini_model_access"] = "ok"
            except Exception as exc:
                result["checks"]["gemini_model_access"] = type(exc).__name__
    print(json.dumps(result, indent=2))
    return all(value == "ok" for value in result["checks"].values())


def _db_check(session, text):
    with session() as db:
        db.execute(text("SELECT 1"))


async def evaluate(path: Path):
    dataset = json.loads(path.read_text())
    report = {"kind": "retrieval_evaluation", "queries": []}
    async with httpx.AsyncClient(timeout=30) as client:
        literature, search = Literature(client), ElasticSearch(client)
        for row in dataset:
            claim = Claim(id="c1", text=row["query"], start=0, end=1, search_terms=row["search_terms"])
            passages, provenance = await literature.discover(claim)
            indexing = await search.index(passages)
            entry = {"query": row["query"], "expected_paper_ids": row.get("expected_paper_ids", []),
                     "provenance": provenance, "indexing": indexing}
            for name, hybrid in [("keyword", False), ("hybrid", True)]:
                results, mode = await search.retrieve(row["query"], provenance["candidate_ids"], hybrid=hybrid)
                ids = [p.paper_id for p in results[:5]]
                expected = set(row.get("expected_paper_ids", []))
                entry[name] = {"actual_mode": mode, "top_five": ids,
                    "hit_at_five": bool(expected.intersection(ids)) if expected else None,
                    "unreviewed": not bool(expected)}
            report["queries"].append(entry)
    output = Path("artifacts/retrieval-evaluation.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(str(output))


def main():
    parser = argparse.ArgumentParser(description="HypeCheck infrastructure operations")
    parser.add_argument("command", choices=["init-db", "setup-elastic", "preflight", "evaluate", "export"])
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        print("Database schema ready")
    elif args.command == "setup-elastic":
        async def setup():
            async with httpx.AsyncClient(timeout=60) as client:
                await ElasticSearch(client).provision()
        asyncio.run(setup())
        print("Elasticsearch index and inference configuration validated")
    elif args.command == "preflight":
        raise SystemExit(0 if asyncio.run(preflight()) else 1)
    elif args.command == "evaluate":
        init_db()
        asyncio.run(evaluate(Path(args.argument or "evaluation/queries.json")))
    elif args.command == "export":
        if not args.argument:
            parser.error("export requires a case UUID")
        from app.replay import export_case
        print(export_case(args.argument))


if __name__ == "__main__":
    main()
