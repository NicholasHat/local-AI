"""Contract tests for the FastAPI layer — TestClient + mocked ollama_client,
the same seam test_agent.py uses. No live model needed."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import conversations
import ollama_client
import server
import skills
import vectorstore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(conversations, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(server, "_active_conversation_id", None)
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


def test_new_conversation_starts_fresh_but_keeps_history(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    old_id = client.get("/api/conversations").json()[0]["id"]

    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    new_id = resp.json()["id"]
    assert new_id != old_id

    roles = [m["role"] for m in client.get("/api/conversation").json()]
    assert roles == ["system"]

    ids = {m["id"] for m in client.get("/api/conversations").json()}
    assert ids == {old_id, new_id}  # old conversation preserved, not wiped


def test_activate_conversation_switches_active(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "first"})
    first_id = client.get("/api/conversations").json()[0]["id"]
    client.post("/api/conversations")  # switches active to a new empty one

    resp = client.post(f"/api/conversations/{first_id}/activate")
    assert resp.status_code == 200

    messages = client.get("/api/conversation").json()
    assert any(m.get("content") == "first" for m in messages)


def test_active_conversation_reflects_current(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    active = client.get("/api/conversations/active").json()

    new_meta = client.post("/api/conversations").json()
    assert new_meta["id"] != active["id"]
    assert client.get("/api/conversations/active").json()["id"] == new_meta["id"]


def test_activate_missing_conversation_404s(client):
    resp = client.post("/api/conversations/does-not-exist/activate")
    assert resp.status_code == 404


def test_delete_conversation_removes_from_history(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    conversation_id = client.get("/api/conversations").json()[0]["id"]

    resp = client.delete(f"/api/conversations/{conversation_id}")
    assert resp.status_code == 200
    assert client.get("/api/conversations").json() == []


def test_delete_missing_conversation_404s(client):
    resp = client.delete("/api/conversations/does-not-exist")
    assert resp.status_code == 404


def test_deleting_active_conversation_falls_back(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health_check", lambda: True)
    monkeypatch.setattr(ollama_client, "chat", _mock_chat_reply("ack"))

    client.post("/api/chat", json={"message": "hi"})
    active_id = client.get("/api/conversations").json()[0]["id"]

    client.delete(f"/api/conversations/{active_id}")
    # Chatting again must not 500 — a fresh active conversation gets created.
    resp = client.post("/api/chat", json={"message": "hi again"})
    assert resp.status_code == 200


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


def test_delete_document_removes_file_and_index(
    client, tmp_path, monkeypatch, text_pdf
):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    monkeypatch.setattr(config, "get_chroma_path", lambda: tmp_path / "chroma")
    vectorstore._client = None
    monkeypatch.setattr(ollama_client, "embed", lambda text, model=None: [0.0] * 8)

    client.post(
        "/api/upload",
        files={"file": ("resume.pdf", text_pdf.read_bytes(), "application/pdf")},
    )

    resp = client.delete("/api/documents/resume.pdf")
    assert resp.status_code == 200
    assert client.get("/api/documents").json() == []
    assert not (upload_dir / "resume.pdf").exists()

    vectorstore._client = None


def test_delete_missing_document_404s(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "get_upload_dir", lambda: tmp_path / "uploads")
    resp = client.delete("/api/documents/does-not-exist.pdf")
    assert resp.status_code == 404


def test_delete_document_rejects_path_traversal(client, tmp_path, monkeypatch):
    """A literal '..' segment has no `.name` component (Path('..').name == ''),
    which the endpoint's safe_name != filename check must reject. Percent-
    encode the dots (%2e) so httpx's own URL normalization doesn't collapse
    the segment client-side before the request is even sent — a literal
    '..' or '/' never reaches the server at all, since normalization and
    routing strip it first, but defense-in-depth here still matters in case
    a client or proxy ever forwards one through unnormalized."""
    monkeypatch.setattr(config, "get_upload_dir", lambda: tmp_path / "uploads")
    resp = client.delete("/api/documents/%2e%2e")
    assert resp.status_code == 400


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


def test_model_library_lists_curated_models(client):
    resp = client.get("/api/models/library")
    assert resp.status_code == 200
    names = {m["name"] for m in resp.json()}
    assert "qwen2.5" in names
    assert all("tool_capable" in m for m in resp.json())


def test_pull_model_streams_progress(client, monkeypatch):
    def fake_pull(name):
        yield {"status": "pulling manifest"}
        yield {"status": "success"}

    monkeypatch.setattr(ollama_client, "pull_model", fake_pull)
    resp = client.post("/api/models/pull", json={"name": "qwen2.5"})
    assert resp.status_code == 200
    assert "pulling manifest" in resp.text
    assert "success" in resp.text


def test_pull_model_failure_streams_error_event_not_abort(client, monkeypatch):
    """A pull that fails mid-stream (unknown model, registry error) must be
    reported as a structured error event, not by aborting the response — an
    aborted chunked stream surfaces in the browser as an opaque 'network
    error' that hides the real cause."""

    def failing_pull(name):
        yield {"status": "pulling manifest"}
        raise RuntimeError("model 'nope' not found")

    monkeypatch.setattr(ollama_client, "pull_model", failing_pull)
    resp = client.post("/api/models/pull", json={"name": "nope"})
    assert resp.status_code == 200
    assert "pulling manifest" in resp.text
    assert '"status": "error"' in resp.text
    assert "model 'nope' not found" in resp.text


def test_delete_model_endpoint(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        ollama_client, "delete_model", lambda name: captured.setdefault("name", name)
    )
    resp = client.delete("/api/models/qwen2.5")
    assert resp.status_code == 200
    assert captured["name"] == "qwen2.5"


def test_delete_model_404s_on_failure(client, monkeypatch):
    def fake_delete(name):
        raise ValueError("not found")

    monkeypatch.setattr(ollama_client, "delete_model", fake_delete)
    resp = client.delete("/api/models/does-not-exist")
    assert resp.status_code == 404


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


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "web" / "dist").exists(),
    reason="web/dist not built (run `cd web && npm run build`)",
)
def test_static_mount_serves_built_frontend_without_shadowing_api(client):
    """The web/dist static mount must be registered LAST — otherwise a `/`
    mount would shadow every /api/* route (CLAUDE.md gotcha)."""
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]

    api = client.get("/api/health")
    assert api.status_code == 200
    assert set(api.json()) == {"healthy", "model"}
