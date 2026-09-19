from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.db import read_case, update_case
from app.media import MediaError
from app.models import MockModels
from app.pipeline import run_case
from app.schemas import Citation, Verdict


@pytest.fixture
def pipeline_mocks(monkeypatch, tmp_path, passage):
    import app.pipeline as pipeline
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video fixture")
    monkeypatch.setattr(pipeline, "download", AsyncMock(return_value=video))
    monkeypatch.setattr(pipeline, "extract_audio", AsyncMock(return_value=(video, 30.0)))
    discover = AsyncMock(return_value=([passage], {"candidate_ids": [passage.paper_id], "papers_found": 1, "cache_hits": 0}))
    monkeypatch.setattr(pipeline.Literature, "discover", discover)
    monkeypatch.setattr(pipeline.ElasticSearch, "index", AsyncMock(return_value={"index_mode": "hybrid"}))
    monkeypatch.setattr(pipeline.ElasticSearch, "retrieve", AsyncMock(return_value=([passage], "hybrid")))
    return discover


async def test_full_mock_pipeline_persists_real_contract(case_id, pipeline_mocks):
    await run_case(case_id)
    case = read_case(case_id)
    assert case["status"] == "complete"
    assert case["result"]["model_mode"] == "mock"
    claim = case["result"]["claims"]["c1"]
    assert claim["verdict"]["label"] == "uncertain"
    assert "Mock" in claim["verdict"]["explanation"]
    assert claim["evidence"][0]["id"] == "p1"
    assert case["result"]["timings"]["total"] >= 0
    await run_case(case_id)
    assert pipeline_mocks.call_count == 1  # Completed jobs are idempotent.


async def test_download_failure_requires_upload(case_id, monkeypatch):
    import app.pipeline
    monkeypatch.setattr(app.pipeline, "download", AsyncMock(side_effect=MediaError("Upload needed")))
    await run_case(case_id)
    assert read_case(case_id)["status"] == "awaiting_upload"
    assert read_case(case_id)["error"]["code"] == "download_blocked"


async def test_research_failure_never_becomes_uncertain(case_id, pipeline_mocks, monkeypatch):
    import app.pipeline
    monkeypatch.setattr(app.pipeline.Literature, "discover", AsyncMock(side_effect=TimeoutError()))
    await run_case(case_id)
    case = read_case(case_id)
    assert case["status"] == "incomplete"
    assert "verdict" not in case["result"]["claims"]["c1"]


async def test_invalid_citation_preserves_evidence(case_id, pipeline_mocks, monkeypatch):
    import app.pipeline
    adapter = MockModels()
    adapter.judge = AsyncMock(return_value=Verdict(label="supports", explanation="Invalid quote", citations=[
        Citation(passage_id="p1", quote="Not in evidence")], limitations=[]))
    monkeypatch.setattr(app.pipeline, "models", lambda: adapter)
    await run_case(case_id)
    case = read_case(case_id)
    assert case["status"] == "incomplete"
    item = case["result"]["claims"]["c1"]
    assert item["evidence"][0]["id"] == "p1" and "verdict" not in item


async def test_no_claims(case_id, pipeline_mocks, monkeypatch):
    import app.pipeline
    adapter = MockModels()
    analysis = await adapter.analyze(Path("unused"))
    analysis.claims = []
    adapter.analyze = AsyncMock(return_value=analysis)
    monkeypatch.setattr(app.pipeline, "models", lambda: adapter)
    await run_case(case_id)
    assert read_case(case_id)["status"] == "no_claims"
    pipeline_mocks.assert_not_awaited()


async def test_resume_after_research_checkpoint(case_id, pipeline_mocks, monkeypatch, passage, tmp_path):
    import app.pipeline
    analysis = await MockModels().analyze(Path("unused"))
    update_case(case_id, status="judging", media_path=str(tmp_path / "existing.mp4"), result_patch={
        "analysis": analysis.model_dump(), "claims": {"c1": {"claim": analysis.claims[0].model_dump(),
            "evidence": [passage.model_dump()], "status": "researched", "timings": {}}},
    })
    await run_case(case_id)
    assert read_case(case_id)["status"] == "complete"
    pipeline_mocks.assert_not_awaited()
    app.pipeline.extract_audio.assert_not_awaited()


async def test_model_mode_change_cannot_relabel_a_mock_transcript(case_id, pipeline_mocks):
    from app.config import settings
    analysis = await MockModels().analyze(Path("unused"))
    update_case(case_id, status="researching", result_patch={"analysis": analysis.model_dump()})
    settings().model_mode = "live"
    await run_case(case_id)
    result = read_case(case_id)
    assert result["status"] == "incomplete"
    assert result["error"]["code"] == "model_configuration_changed"
    assert result["result"]["model_mode"] == "mock"


async def test_three_cases_run_with_isolated_evidence(client, pipeline_mocks):
    import asyncio
    ids = [client.post("/api/cases", json={"source_url": f"https://instagram.com/reel/test{i}/"}).json()["id"] for i in range(3)]
    await asyncio.gather(*(run_case(case_id) for case_id in ids))
    assert all(read_case(case_id)["status"] == "complete" for case_id in ids)
    assert pipeline_mocks.call_count == 3


async def test_hard_timeout_marks_all_unfinished_claims_incomplete(case_id, pipeline_mocks, monkeypatch):
    import asyncio

    import app.pipeline
    from app.config import settings

    settings().case_timeout_seconds = 0.05
    async def slow(*args):
        await asyncio.sleep(2)
    monkeypatch.setattr(app.pipeline.Literature, "discover", slow)
    await run_case(case_id)
    case = read_case(case_id)
    assert case["status"] == "incomplete"
    assert case["result"]["claims"]["c1"]["status"] == "incomplete"
    assert "verdict" not in case["result"]["claims"]["c1"]


async def test_primary_outage_preserves_sources_without_judgment(case_id, pipeline_mocks, monkeypatch, passage):
    import app.pipeline
    from app.literature import DiscoveryIncomplete

    provenance = {'provider_failures': [{'provider': 'Europe PMC', 'error': 'ReadTimeout'}]}
    pipeline_mocks.side_effect = DiscoveryIncomplete([passage], provenance)
    adapter = MockModels()
    adapter.judge = AsyncMock()
    monkeypatch.setattr(app.pipeline, 'models', lambda: adapter)
    await run_case(case_id)
    case = read_case(case_id)
    item = case['result']['claims']['c1']
    assert case['status'] == 'incomplete'
    assert item['provenance'] == provenance
    assert item['discovered_sources'][0]['source_url'] == passage.source_url
    assert 'verdict' not in item
    adapter.judge.assert_not_awaited()


async def test_supplement_failure_is_disclosed_in_verdict(case_id, pipeline_mocks, passage):
    pipeline_mocks.return_value = ([passage], {
        'candidate_ids': [passage.id],
        'provider_failures': [{'provider': 'MedlinePlus', 'error': 'TimeoutError'}],
    })
    await run_case(case_id)
    case = read_case(case_id)
    assert case['status'] == 'complete'
    assert any('MedlinePlus was unavailable' in item
               for item in case['result']['claims']['c1']['verdict']['limitations'])
