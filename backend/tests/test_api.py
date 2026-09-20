import json

from app.db import read_case, update_case


def test_api_creation_and_progress(client, case_id):
    initial = client.get(f"/api/cases/{case_id}").json()
    assert initial["status"] == "queued"
    assert initial["sequence"] == 1
    assert initial["result"]["model_mode"] == "mock"
    update_case(case_id, status="researching")
    update_case(case_id, status="complete")
    response = client.get(f"/api/cases/{case_id}/events", headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    assert "id: 1\n" not in response.text
    assert "id: 2\n" in response.text and "id: 3\n" in response.text
    assert "event: end" in response.text


def test_upload_resumes_same_case(client, case_id):
    update_case(case_id, status="awaiting_upload")
    response = client.post(f"/api/cases/{case_id}/media", files={"file": ("video.mp4", b"pretend", "video/mp4")})
    assert response.status_code == 202
    assert response.json()["id"] == case_id
    assert response.json()["status"] == "queued"
    assert client.post(f"/api/cases/{case_id}/media", files={"file": ("video.mp4", b"again")}).status_code == 409


def test_upload_limits_and_empty(client, case_id, monkeypatch):
    import app.main
    monkeypatch.setattr(app.main, "MAX_BYTES", 4)
    update_case(case_id, status="awaiting_upload")
    assert client.post(f"/api/cases/{case_id}/media", files={"file": ("a", b"12345")}).status_code == 413
    assert client.post(f"/api/cases/{case_id}/media", files={"file": ("a", b"")}).status_code == 422
    assert read_case(case_id)["status"] == "awaiting_upload"


def test_queue_limit(client):
    from app.config import settings
    settings().max_active_cases = 2
    for _ in range(2):
        assert client.post("/api/cases", json={"source_url": "https://instagram.com/reel/abc"}).status_code == 202
    assert client.post("/api/cases", json={"source_url": "https://instagram.com/reel/abc"}).status_code == 429


def test_rate_limit(client):
    from app.config import settings
    settings().rate_limit_per_minute = 1
    assert client.post("/api/cases", json={"source_url": "https://instagram.com/reel/abc"}).status_code == 202
    assert client.post("/api/cases", json={"source_url": "https://instagram.com/reel/def"}).status_code == 429


def test_missing_and_invalid_cases(client):
    assert client.get("/api/cases/not-a-uuid").status_code == 404
    assert client.get("/api/cases/00000000-0000-0000-0000-000000000000").status_code == 404


def test_failure_injection_requires_admin_and_enable(client):
    from app.config import settings
    assert client.post("/api/admin/failure").status_code == 401
    auth = {"Authorization": "Bearer test-admin"}
    assert client.post("/api/admin/failure", headers=auth).status_code == 404
    settings().enable_failure_injection = True
    assert client.post("/api/admin/failure", headers=auth).status_code == 503


def test_sentry_demo_is_protected_and_disabled_by_default(client):
    from app.config import settings
    assert client.post("/api/admin/sentry-demo").status_code == 401
    auth = {"Authorization": "Bearer test-admin"}
    assert client.post("/api/admin/sentry-demo", headers=auth).status_code == 404
    settings().sentry_demo_enabled = True
    settings().sentry_dsn = "https://public@sentry.example/1"
    response = client.post("/api/admin/sentry-demo", headers=auth)
    assert response.status_code == 503
    body = response.json()
    assert body["demo"] is True
    assert body["products"]["session_replay"].startswith("browser-only")


def test_offline_export_escapes_html(client, case_id):
    update_case(case_id, status="complete", result_patch={"untrusted": "</script><script>alert('x')</script>"})
    response = client.get(f"/api/cases/{case_id}/replay")
    assert response.status_code == 200
    assert "</script><script>alert('x')" not in response.text
    assert "OFFLINE REPLAY" in response.text
    payload = client.get(f"/api/cases/{case_id}/replay?format=json").json()
    assert payload["replay"] is True
    assert payload["case"]["id"] == case_id
    assert len(payload["events"]) == 2


def test_pubsub_failure_does_not_lose_events(client, case_id, monkeypatch):
    import app.queue
    def fail():
        raise ConnectionError("Redis unavailable")
    monkeypatch.setattr(app.queue, "redis_client", fail)
    update_case(case_id, status="complete")
    response = client.get(f"/api/cases/{case_id}/events")
    data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
    assert any(event.get("status") == "complete" for event in data)
