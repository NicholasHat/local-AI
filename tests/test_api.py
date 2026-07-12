"""Contract tests for the FastAPI layer — TestClient + mocked ollama_client,
the same seam test_agent.py uses. No live model needed."""

import pytest
from fastapi.testclient import TestClient

import config
import ollama_client
import server
import skills
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


@pytest.fixture
def isolated_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")
    return tmp_path / "skills"


def test_list_skills_empty(client, isolated_skills_dir):
    assert client.get("/api/skills").json() == []


def test_create_and_list_instruction_skill(client, isolated_skills_dir):
    resp = client.post(
        "/api/skills",
        json={
            "name": "greet",
            "description": "Greets someone",
            "parameters": {"name": {"type": "string"}},
            "required": ["name"],
            "prompt": "Say hello to {name}.",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "instruction"

    listed = client.get("/api/skills").json()
    assert listed == [
        {
            "name": "greet",
            "description": "Greets someone",
            "kind": "instruction",
            "parameters": {"name": {"type": "string"}},
            "required": ["name"],
            "body": "Say hello to {name}.",
        }
    ]


def test_create_code_skill_via_api(client, isolated_skills_dir):
    resp = client.post(
        "/api/skills",
        json={
            "name": "word-count",
            "description": "Counts words",
            "parameters": {"text": {"type": "string"}},
            "required": ["text"],
            "code": "def run(text):\n    return str(len(text.split()))\n",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "code"


def test_create_skill_requires_exactly_one_of_prompt_or_code(
    client, isolated_skills_dir
):
    resp = client.post("/api/skills", json={"name": "bad", "description": "d"})
    assert resp.status_code == 400


def test_update_skill_overwrites(client, isolated_skills_dir):
    client.post(
        "/api/skills",
        json={"name": "greet", "description": "v1", "prompt": "Hi {name}"},
    )
    resp = client.put(
        "/api/skills/greet",
        json={"name": "greet", "description": "v2", "prompt": "Hello {name}!"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "v2"


def test_update_skill_rejects_name_mismatch(client, isolated_skills_dir):
    resp = client.put(
        "/api/skills/greet",
        json={"name": "other", "description": "d", "prompt": "p"},
    )
    assert resp.status_code == 400


def test_delete_skill(client, isolated_skills_dir):
    client.post(
        "/api/skills", json={"name": "greet", "description": "d", "prompt": "p"}
    )
    resp = client.delete("/api/skills/greet")
    assert resp.status_code == 200
    assert client.get("/api/skills").json() == []


def test_delete_missing_skill_404s(client, isolated_skills_dir):
    resp = client.delete("/api/skills/does-not-exist")
    assert resp.status_code == 404


def test_created_skill_is_immediately_usable_via_chat(
    client, isolated_skills_dir, monkeypatch
):
    """The CRUD API and the agent loop share one registry — a skill created
    through the API must be callable on the very next chat turn, with no
    caching layer to invalidate."""
    client.post(
        "/api/skills",
        json={
            "name": "greet",
            "description": "Greets someone",
            "parameters": {"name": {"type": "string"}},
            "required": ["name"],
            "prompt": "Say hello to {name}.",
        },
    )

    monkeypatch.setattr(ollama_client, "health_check", lambda: True)

    state = {"n": 0}

    def fake_chat(messages, tools=None, model=None):
        names = [t["function"]["name"] for t in tools]
        assert "skill__greet" in names
        state["n"] += 1
        if state["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "skill__greet", "arguments": {"name": "Ada"}}}
                ],
            }
        return {"role": "assistant", "content": "done", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    resp = client.post("/api/chat", json={"message": "greet Ada"})
    assert resp.status_code == 200

    transcript = client.get("/api/conversation").json()
    tool_msg = next(m for m in transcript if m["role"] == "tool")
    assert tool_msg["content"] == "Say hello to Ada."
