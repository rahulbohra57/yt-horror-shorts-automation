import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    from app.core import models  # ensure models loaded
    from app.core.config import settings
    from app.core.database import init_db
    init_db(settings.DB_PATH)
    return TestClient(app)


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_niches(client):
    resp = client.get("/api/niches")
    assert resp.status_code == 200
    data = resp.json()
    assert "niches" in data
    assert "horror" in data["niches"]
    assert "mystery" in data["niches"]


def test_list_shorts_empty_or_list(client):
    resp = client.get("/api/shorts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_generate_endpoint_creates_job(client):
    resp = client.post("/api/generate", json={"niche": "horror", "upload": False})
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"


def test_invalid_niche_returns_422(client):
    resp = client.post("/api/generate", json={"niche": "unknown_niche", "upload": False})
    assert resp.status_code == 422


def test_get_short_not_found(client):
    resp = client.get("/api/shorts/999999")
    assert resp.status_code == 404
