"""Live-model E2E coverage for model listing and selection.

Same live-Ollama gate as the rest of tests/e2e/ (see tests/e2e/conftest.py).
"""

import pytest
from fastapi.testclient import TestClient

import ollama_client
import server

pytestmark = pytest.mark.e2e


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_conversation", None)
    monkeypatch.setattr(server, "_selected_model", None)
    return TestClient(server.app)


def test_list_models_reflects_real_installed_models_e2e():
    models = ollama_client.list_models()
    by_name = {m["name"]: m for m in models}
    assert any("qwen2.5" in name for name in by_name)

    qwen = next(m for name, m in by_name.items() if "qwen2.5" in name)
    assert "tools" in qwen["capabilities"]

    embed = next((m for name, m in by_name.items() if "nomic-embed" in name), None)
    if embed is not None:
        assert "tools" not in embed["capabilities"]


def test_select_tool_capable_model_reflected_in_health_e2e(client):
    models = client.get("/api/models").json()["models"]
    tool_capable = [m for m in models if m["tool_capable"]]
    assert tool_capable, "expected at least one tool-capable installed model"

    target = tool_capable[0]["name"]
    resp = client.post("/api/settings/model", json={"model": target})
    assert resp.status_code == 200
    assert resp.json()["current"] == target
    assert client.get("/api/health").json()["model"] == target


def test_select_non_tool_capable_model_rejected_e2e(client):
    models = client.get("/api/models").json()["models"]
    non_tool = next((m for m in models if not m["tool_capable"]), None)
    if non_tool is None:
        pytest.skip("no non-tool-capable model installed to test rejection against")

    resp = client.post("/api/settings/model", json={"model": non_tool["name"]})
    assert resp.status_code == 400


def test_second_tool_capable_model_answers_e2e(client):
    models = client.get("/api/models").json()["models"]
    tool_capable = [m["name"] for m in models if m["tool_capable"]]
    if len(tool_capable) < 2:
        pytest.skip("only one tool-capable model installed; nothing to compare")

    client.post("/api/settings/model", json={"model": tool_capable[1]})
    resp = client.post(
        "/api/chat", json={"message": "Say the single word: acknowledged."}
    )
    assert resp.status_code == 200
    assert resp.json()["reply"]
