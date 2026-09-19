import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("ELASTICSEARCH_URL", "https://elastic.test")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "test-key")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "100")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("ENABLE_FAILURE_INJECTION", "false")
    from app.config import settings
    from app.db import engine, init_db
    settings.cache_clear()
    engine.cache_clear()
    init_db()
    import fakeredis

    import app.main
    import app.queue
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(app.queue, "redis_client", lambda: fake)
    monkeypatch.setattr(app.main, "redis_client", lambda: fake)
    monkeypatch.setattr(app.main, "enqueue", lambda case_id: None)
    yield fake
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def client(isolated):
    from app.main import app
    with TestClient(app) as value:
        yield value


@pytest.fixture
def passage():
    from app.schemas import Passage
    text = "Routine vitamin C supplementation did not reduce the incidence of the common cold."
    return Passage(id="p1", paper_id="MED:123", title="Vitamin C review", source_url="https://europepmc.org/article/MED/123",
                   published="2020-01-01", study_types=["Systematic Review"], access_type="abstract_only",
                   section="Abstract", text=text, context=text, start=0, end=len(text))


@pytest.fixture
def case_id(client):
    response = client.post("/api/cases", json={"source_url": "https://www.instagram.com/reel/test123/"})
    assert response.status_code == 202
    return response.json()["id"]
