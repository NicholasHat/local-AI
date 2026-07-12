"""Live-model E2E variant of the tool suite, exercised through the HTTP API
layer instead of calling agent.run() directly — proves the API boundary adds
no behavior change. Same live-Ollama gate as tests/e2e/conftest.py (see
tests/e2e/test_tools_e2e.py for the tool-level equivalents and the reasoning
behind the loose, tool-usage-based assertions).
"""

import pytest
from fastapi.testclient import TestClient

import config
import server
import vectorstore

pytestmark = pytest.mark.e2e


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_conversation", None)
    return TestClient(server.app)


def test_health_e2e(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["healthy"] is True


def test_chat_forces_get_time_tool_e2e(client, monkeypatch):
    """Retry a few times: whether the model calls get_time for a given prompt
    is a judgment call it doesn't make identically every time (see the same
    reasoning in tests/e2e/test_tools_e2e.py's _run_forcing_tool)."""
    message = {
        "message": "What is the exact current time in UTC right now? Call "
        "your time tool rather than guessing, then tell me the hour and minute."
    }
    for _ in range(3):
        monkeypatch.setattr(server, "_conversation", None)
        resp = client.post("/api/chat", json=message)
        assert resp.status_code == 200
        reply = resp.json()["reply"]

        transcript = client.get("/api/conversation").json()
        tool_names = [m["tool_name"] for m in transcript if m["role"] == "tool"]
        if "get_time" in tool_names:
            assert any(ch.isdigit() for ch in reply)
            return
    raise AssertionError("get_time never called in 3 attempts")


def test_upload_then_search_via_api_e2e(client, tmp_path, monkeypatch, text_pdf):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    monkeypatch.setattr(config, "get_chroma_path", lambda: tmp_path / "chroma")
    vectorstore._client = None

    resp = client.post(
        "/api/upload",
        files={"file": ("resume.pdf", text_pdf.read_bytes(), "application/pdf")},
    )
    assert resp.status_code == 200

    resp = client.post(
        "/api/chat",
        json={
            "message": "Search my uploaded documents and tell me exactly what "
            "text is in resume.pdf."
        },
    )
    assert "hello rag world" in resp.json()["reply"].lower()

    vectorstore._client = None
