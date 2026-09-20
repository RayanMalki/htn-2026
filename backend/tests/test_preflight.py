import json

import pytest
import respx

from app.cli import preflight
from app.config import settings


@respx.mock
@pytest.mark.parametrize("missing", [
    ["ELASTICSEARCH_URL"], ["ELASTICSEARCH_API_KEY"],
    ["ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY"],
])
async def test_missing_elastic_configuration_is_actionable_and_makes_no_requests(missing, capsys):
    cfg = settings()
    for name in missing:
        setattr(cfg, name.lower(), " ")
    assert await preflight() is False
    report = json.loads(capsys.readouterr().out)
    for name in ("elastic_index", "elastic_inference"):
        assert report["checks"][name] == "not_configured"
        assert report["details"][name]["missing"] == missing
        assert "Recreate" in report["details"][name]["hint"]
    assert not respx.calls


@respx.mock
@pytest.mark.parametrize("status", [200, 401, 403, 404, 503])
async def test_elastic_preflight_reports_status_without_leaking_secrets(status, capsys):
    cfg = settings()
    cfg.elasticsearch_url = "https://elastic.test/secret-url-segment"
    cfg.elasticsearch_api_key = "secret-api-key"
    for path in (f"/{cfg.elastic_index}/_mapping", f"/_inference/{cfg.elastic_inference_id}"):
        respx.get(cfg.elasticsearch_url + path).respond(status, json={"error": "secret-response-body"})
    assert await preflight() is (status == 200)
    output = capsys.readouterr().out
    report = json.loads(output)
    for name in ("elastic_index", "elastic_inference"):
        assert report["checks"][name] == ("ok" if status == 200 else f"HTTP {status}")
    if status == 404:
        assert "setup-elastic" in report["details"]["elastic_index"]["hint"]
        assert "ELASTIC_INFERENCE_ID" in report["details"]["elastic_inference"]["hint"]
    assert "secret-" not in output


@respx.mock
async def test_keyword_preflight_skips_inference(capsys):
    cfg = settings()
    cfg.elastic_semantic = False
    respx.get(f"{cfg.elasticsearch_url}/{cfg.elastic_index}/_mapping").respond(200, json={})
    assert await preflight() is True
    report = json.loads(capsys.readouterr().out)
    assert "elastic_inference" not in report["checks"]
    assert len(respx.calls) == 1
