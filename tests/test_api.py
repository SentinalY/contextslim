"""FastAPI surface. Same service layer, different transport."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contextslim.api import create_app
from contextslim.service import ContextSlimService


@pytest.fixture
def client(settings):
    with TestClient(create_app(ContextSlimService(settings))) as test_client:
        yield test_client


@pytest.fixture
def session_id(client, sample_chat) -> str:
    response = client.post("/capsules", json={"chat_history": sample_chat})
    assert response.status_code == 201
    return response.json()["session_id"]


# --- diagnostics -----------------------------------------------------------


def test_health_endpoint(client):
    payload = client.get("/health").json()
    assert payload["ok"] is True
    assert payload["deep_mode_available"] is False


def test_openapi_schema_is_generated(client):
    schema = client.get("/openapi.json").json()
    assert "/capsules" in schema["paths"]
    assert "/capsules/{session_id}" in schema["paths"]


# --- extract / load --------------------------------------------------------


def test_extract_returns_201_with_metrics(client, sample_chat):
    response = client.post("/capsules", json={"chat_history": sample_chat})
    assert response.status_code == 201
    body = response.json()
    assert body["ok"] is True
    assert body["metrics"]["reduction_pct"] > 50


def test_extract_with_empty_body_is_400(client):
    response = client.post("/capsules", json={"chat_history": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_input"


def test_extract_with_bad_mode_is_400(client, sample_chat):
    response = client.post("/capsules", json={"chat_history": sample_chat, "mode": "turbo"})
    assert response.status_code == 400


def test_load_capsule(client, session_id):
    body = client.get(f"/capsules/{session_id}").json()
    assert body["session_id"] == session_id
    assert "CONTEXT CAPSULE RESTORED" in body["restore_prompt"]


def test_load_unknown_capsule_is_404(client):
    response = client.get("/capsules/ZZZZZZZZ")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "capsule_not_found"


# --- list / search ---------------------------------------------------------


def test_list_capsules(client, session_id):
    body = client.get("/capsules").json()
    assert body["count"] == 1
    assert body["capsules"][0]["session_id"] == session_id


def test_list_respects_limit_validation(client):
    assert client.get("/capsules", params={"limit": 0}).status_code == 422


def test_search_route_is_not_shadowed_by_the_id_route(client, session_id):
    body = client.get("/capsules/search", params={"q": "PostgreSQL"}).json()
    assert body["count"] == 1
    assert body["capsules"][0]["session_id"] == session_id


def test_search_requires_a_query(client):
    assert client.get("/capsules/search", params={"q": ""}).status_code == 422


# --- update / versions -----------------------------------------------------


def test_update_capsule(client, session_id):
    response = client.patch(
        f"/capsules/{session_id}",
        json={"chat_history": "Decision: we chose Locust for load testing."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert any("Locust" in item for item in body["capsule"]["decisions"])


def test_update_unknown_capsule_is_404(client):
    response = client.patch("/capsules/ZZZZZZZZ", json={"chat_history": "text"})
    assert response.status_code == 404


def test_versions_endpoint(client, session_id):
    client.patch(f"/capsules/{session_id}", json={"chat_history": "More work.", "note": "b2"})
    body = client.get(f"/capsules/{session_id}/versions").json()
    assert body["count"] == 1
    assert body["versions"][0]["note"] == "b2"


# --- export ----------------------------------------------------------------


def test_export_capsule(client, session_id, tmp_path):
    target = tmp_path / "capsule.txt"
    response = client.post(
        f"/capsules/{session_id}/export",
        json={"format": "txt", "destination": str(target)},
    )
    assert response.status_code == 200
    assert target.exists()


def test_export_bad_format_is_400(client, session_id):
    response = client.post(f"/capsules/{session_id}/export", json={"format": "pdf"})
    assert response.status_code == 400


# --- analytics -------------------------------------------------------------


def test_stats_endpoint(client, session_id):
    body = client.get("/stats").json()
    assert body["total_sessions"] == 1
    assert body["total_tokens_saved"] > 0


def test_context_health_endpoint(client):
    body = client.post("/context/health", json={"token_count": 94_000}).json()
    assert body["status"] == "CRITICAL"
    assert body["should_compress"] is True


def test_context_health_requires_input(client):
    assert client.post("/context/health", json={}).status_code == 400
