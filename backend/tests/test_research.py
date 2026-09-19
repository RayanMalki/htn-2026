import json

import httpx
import pytest
import respx

from app.config import settings
from app.literature import BASE, MEDLINEPLUS_BASE, Literature, build_query, chunks
from app.schemas import Claim
from app.search import ElasticSearch, diversify


def test_passage_split_keeps_offsets(passage):
    meta = passage.model_dump(exclude={"id", "section", "text", "context", "start", "end"})
    found = chunks(meta, [("Results", "A valid result sentence. " * 150)])
    assert len(found) > 1
    for chunk in found:
        assert chunk.context[chunk.start:chunk.end] == chunk.text
    assert len({p.id for p in found}) == len(found)


def test_diversity_limit(passage):
    candidates = [passage.model_copy(update={"id": str(i), "paper_id": f"MED:{i // 4}"}) for i in range(20)]
    results = diversify(candidates)
    assert len(results) == 6
    assert [p.paper_id for p in results].count("MED:0") == 2


def test_query_does_not_accept_model_operators():
    query = build_query(["vitamin C OR *:*", "cold"])
    assert "*:*" not in query and "TITLE_ABS" in query


@respx.mock
async def test_discovery_reserves_candidates_for_each_search_tier():
    settings().medlineplus_enabled = False

    def records(prefix):
        return [{"id": f"{prefix}{i}", "source": "MED", "pmid": f"{prefix}{i}",
                 "title": f"{prefix} result {i}",
                 "abstractText": "A sufficiently long abstract passage for retrieval and testing."}
                for i in range(15)]

    respx.get(f"{BASE}/search").mock(side_effect=[
        httpx.Response(200, json={"resultList": {"result": records("title")}}),
        httpx.Response(200, json={"resultList": {"result": records("review")}}),
        httpx.Response(200, json={"resultList": {"result": records("broad")}}),
    ])
    async with httpx.AsyncClient() as client:
        _, provenance = await Literature(client).discover(Claim(
            id="c1", text="claim", start=0, end=1, search_terms=["medical topic"]))
    ids = provenance["candidate_paper_ids"]
    assert sum(value.startswith("MED:title") for value in ids) == 5
    assert sum(value.startswith("MED:review") for value in ids) == 5
    assert sum(value.startswith("MED:broad") for value in ids) == 5


@respx.mock
async def test_medlineplus_health_topic_is_normalized():
    respx.get(f"{BASE}/search").mock(return_value=httpx.Response(
        200, json={"resultList": {"result": []}}))
    respx.get(MEDLINEPLUS_BASE).mock(return_value=httpx.Response(200, text="""
        <nlmSearchResult><list><document url="https://medlineplus.gov/commoncold.html">
          <content name="title">Common Cold</content>
          <content name="FullSummary">The common cold is a viral infection with symptoms that usually improve over time.</content>
        </document></list></nlmSearchResult>"""))
    async with httpx.AsyncClient() as client:
        evidence, provenance = await Literature(client).discover(Claim(
            id="c1", text="claim", start=0, end=1, search_terms=["common cold"]))
    assert len(evidence) == 1
    assert evidence[0].provider == "medlineplus"
    assert evidence[0].source_kind == "health_topic"
    assert evidence[0].access_type == "summary"
    assert provenance["sources_found"] == 1


@respx.mock
async def test_discovery_retraction_and_abstract_fallback(passage):
    record = {"id": "123", "source": "MED", "pmid": "123", "pmcid": "PMC123", "title": "Vitamin C review",
              "abstractText": passage.text, "isOpenAccess": "Y", "pubTypeList": {"pubType": ["Review"]}}
    respx.get(f"{BASE}/search").mock(return_value=httpx.Response(200, json={"resultList": {"result": [record, record,
        {**record, "id": "456", "pmid": "456", "pubTypeList": {"pubType": ["Retracted Publication"]}}]}}))
    respx.get(MEDLINEPLUS_BASE).mock(return_value=httpx.Response(503))
    full = respx.get(f"{BASE}/PMC123/fullTextXML").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        evidence, provenance = await Literature(client).discover(Claim(id="c1", text="Vitamin C prevents colds", start=0, end=1, search_terms=["vitamin C cold"]))
    assert provenance["papers_found"] == 1
    assert provenance["full_text_fallbacks"] == 1
    assert evidence[0].access_type == "abstract_only"
    assert provenance["provider_failures"][0]["provider"] == "MedlinePlus"
    assert full.call_count == 1


@respx.mock
async def test_full_text_and_cache(passage):
    record = {"id": "123", "source": "MED", "pmcid": "PMC123", "title": "Review", "abstractText": passage.text}
    full = respx.get(f"{BASE}/PMC123/fullTextXML").mock(return_value=httpx.Response(200,
        text=f"<article><body><sec><title>Results</title><p>{passage.text}</p></sec></body></article>"))
    async with httpx.AsyncClient() as client:
        literature = Literature(client)
        first, cached, _ = await literature.paper(record, True)
        second, cached2, _ = await literature.paper(record, True)
    assert first[0].access_type == "full_text" and first[0].section == "Results"
    assert second[0].id == first[0].id and cached == 0 and cached2 == 1
    assert full.call_count == 1


@respx.mock
async def test_hybrid_filter_and_keyword_fallback(passage):
    route = respx.post(f"https://elastic.test/{settings().elastic_index}/_search").mock(side_effect=[
        httpx.Response(400, json={"error": "inference unavailable"}),
        httpx.Response(200, json={"hits": {"hits": [{"_source": passage.model_dump()}]}}),
    ])
    async with httpx.AsyncClient() as client:
        results, mode = await ElasticSearch(client).retrieve("vitamin C", ["p1"])
    assert results[0].id == passage.id and mode == "keyword_only"
    first = json.loads(route.calls[0].request.content)
    retrievers = first["retriever"]["rrf"]["retrievers"]
    assert all(r["standard"]["query"]["bool"]["filter"][0] == {"ids": {"values": ["p1"]}}
               for r in retrievers)
    assert "query" in json.loads(route.calls[1].request.content)


@respx.mock
async def test_index_partial_failure_is_detected(passage):
    index = settings().elastic_index
    respx.post(f"https://elastic.test/{index}/_mget").mock(return_value=httpx.Response(200, json={"docs": []}))
    bulk = respx.post(f"https://elastic.test/{index}/_bulk").mock(side_effect=[
        httpx.Response(200, json={"errors": True, "items": [{"index": {"_id": "p1", "error": {"type": "inference"}}}]}),
        httpx.Response(200, json={"errors": False, "items": [{"index": {"_id": "p1", "status": 201}}]}),
    ])
    async with httpx.AsyncClient() as client:
        result = await ElasticSearch(client).index([passage])
    assert result["index_mode"] == "keyword_only"
    assert bulk.calls[0].request.headers["Content-Type"] == "application/x-ndjson"
    assert '"semantic"' not in bulk.calls[1].request.content.decode()


@respx.mock
async def test_elastic_unavailable_fails_instead_of_empty_evidence():
    respx.post(f"https://elastic.test/{settings().elastic_index}/_search").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await ElasticSearch(client).retrieve("query", ["MED:123"])


@pytest.mark.parametrize('supplement_has_results', [False, True])
async def test_required_provider_failure_is_not_empty_success(monkeypatch, passage, supplement_has_results):
    from unittest.mock import AsyncMock

    from app.literature import DiscoveryIncomplete

    monkeypatch.setattr(Literature, '_europe_pmc', AsyncMock(side_effect=httpx.ReadTimeout('outage')))
    found = [passage] if supplement_has_results else []
    monkeypatch.setattr(Literature, '_medlineplus', AsyncMock(return_value=(found, {
        'provider': 'MedlinePlus', 'sources_found': len(found),
    })))
    async with httpx.AsyncClient() as client:
        with pytest.raises(DiscoveryIncomplete) as caught:
            await Literature(client).discover(Claim(id='c1', text='claim', start=0, end=1, search_terms=['topic']))
    assert caught.value.passages == found
    assert caught.value.provenance['provider_failures'] == [{'provider': 'Europe PMC', 'error': 'ReadTimeout'}]


async def test_supplement_timeout_preserves_primary_results(monkeypatch, passage):
    import asyncio
    from unittest.mock import AsyncMock

    import app.literature as literature

    cancelled = asyncio.Event()

    async def stalled(self, claim):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(literature, 'MEDLINEPLUS_TIMEOUT_SECONDS', 0.01)
    monkeypatch.setattr(Literature, '_medlineplus', stalled)
    monkeypatch.setattr(Literature, '_europe_pmc', AsyncMock(return_value=([passage], {
        'provider': 'Europe PMC', 'sources_found': 1,
    })))
    async with httpx.AsyncClient() as client, asyncio.timeout(1):
        found, provenance = await Literature(client).discover(
            Claim(id='c1', text='claim', start=0, end=1, search_terms=['topic']))
    assert found == [passage]
    assert cancelled.is_set()
    assert provenance['provider_failures'] == [{'provider': 'MedlinePlus', 'error': 'TimeoutError'}]
