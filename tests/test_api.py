"""Contract tests for the FastAPI layer — TestClient + mocked ollama_client,
the same seam test_agent.py uses. No live model needed."""

import pytest
from fastapi.testclient import TestClient

import config
import ollama_client
import server
import vectorstore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_conversation", None)
    monkeypatch.setattr(server, "_selected_model", None)
    return TestClient(server.app)


_FAKE_MODELS = [
    {"name": "qwen2.5:latest", "size": 100, "capabilities": ["completion", "tools"]},
    {"name": "llama3.1:latest", "size": 200, "capabilities": ["completion", "tools"]},
    {"name": "nomic-embed-text:latest", "size": 50, "capabilities": ["embedding"]},
]


def _mock_chat_reply(content: str):
    return lambda messages, tools=None, model=None: {
        "role": "assistant",
        "content": content,
        "tool_calls": None,
    }


def test_health_reports_reachability_and_model(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert body["model"]


def test_health_when_ollama_down(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: False)
    resp = client.get("/api/health")
    assert resp.json()["healthy"] is False


def test_chat_round_trip(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("hello there"))

    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "hello there"


def test_chat_fails_loudly_when_ollama_unreachable(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: False)
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503


def test_conversation_reflects_history(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    roles = [m["role"] for m in client.get("/api/conversation").json()]
    assert roles == ["system", "user", "assistant"]


def test_reset_clears_conversation(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    client.post("/api/conversation/reset")
    roles = [m["role"] for m in client.get("/api/conversation").json()]
    assert roles == ["system"]


def test_upload_ingests_and_lists_document(client, tmp_path, monkeypatch, text_pdf):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    monkeypatch.setattr(config, "get_chroma_path", lambda: tmp_path / "chroma")
    vectorstore._client = None
    monkeypatch.setattr(ollama_client, "embed", lambda text, model=None: [0.0] * 8)

    resp = client.post(
        "/api/upload",
        files={"file": ("resume.pdf", text_pdf.read_bytes(), "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "resume.pdf"
    assert body["chunks"] == 1

    docs = client.get("/api/documents").json()
    assert any(d["filename"] == "resume.pdf" for d in docs)

    vectorstore._client = None


def test_upload_rejects_non_file_body(client):
    resp = client.post("/api/upload", data={"file": "not-a-file"})
    assert resp.status_code == 422


def test_list_models_reports_tool_capability(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: _FAKE_MODELS)
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {m["name"]: m for m in body["models"]}
    assert by_name["qwen2.5:latest"]["tool_capable"] is True
    assert by_name["nomic-embed-text:latest"]["tool_capable"] is False


def test_list_models_resolves_untagged_default_to_tagged_name(client, monkeypatch):
    """config.get_model() ('qwen2.5') is untagged; list_models() reports
    'qwen2.5:latest' — `current` must match one of the listed option names,
    or a frontend <select> bound to it silently falls back to the wrong
    option instead of reflecting the real default."""
    monkeypatch.setattr(ollama_client, "list_models", lambda: _FAKE_MODELS)
    monkeypatch.setattr(config, "get_model", lambda: "qwen2.5")

    resp = client.get("/api/models")
    current = resp.json()["current"]
    assert current == "qwen2.5:latest"
    assert current in {m["name"] for m in resp.json()["models"]}


def test_set_model_switches_current_and_used_in_chat(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: _FAKE_MODELS)
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)

    resp = client.post("/api/settings/model", json={"model": "llama3.1:latest"})
    assert resp.status_code == 200
    assert resp.json()["current"] == "llama3.1:latest"

    assert client.get("/api/health").json()["model"] == "llama3.1:latest"

    captured = {}

    def fake_chat(messages, tools=None, model=None):
        captured["model"] = model
        return {"role": "assistant", "content": "ack", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    client.post("/api/chat", json={"message": "hi"})
    assert captured["model"] == "llama3.1:latest"


def test_set_model_rejects_unknown_model(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: _FAKE_MODELS)
    resp = client.post("/api/settings/model", json={"model": "does-not-exist"})
    assert resp.status_code == 404


def test_set_model_rejects_non_tool_capable_model(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: _FAKE_MODELS)
    resp = client.post("/api/settings/model", json={"model": "nomic-embed-text:latest"})
    assert resp.status_code == 400
