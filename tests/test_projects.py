"""projects.py unit tests (tmp dirs, no live model) plus the chat-context
integration: the ephemeral system message and the document-scoped search."""

import pytest

import agent
import config
import ollama_client
import projects
import settings
import spaces
import vectorstore
from api import projects as projects_api
from memory import Conversation


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    return upload_dir


def test_create_get_list_and_space():
    p = projects.create("Thesis", "Write chapter 3")
    assert p["name"] == "Thesis"
    assert p["goal"] == "Write chapter 3"
    assert p["notes"] == ""
    assert projects.get(p["id"])["id"] == p["id"]
    assert [m.id for m in projects.list_recent()] == [p["id"]]
    assert spaces.get(p["space_id"])["purpose"] == "Write chapter 3"


def test_create_requires_name():
    with pytest.raises(projects.ProjectError):
        projects.create("  ")


def test_get_missing_raises():
    with pytest.raises(projects.ProjectError, match="No such project"):
        projects.get("nope")


def test_update_fields_and_touches_updated_at():
    p = projects.create("A")
    updated = projects.update(p["id"], goal="new goal", notes="# hi")
    assert updated["goal"] == "new goal"
    assert updated["notes"] == "# hi"
    assert updated["name"] == "A"
    assert updated["updated_at"] >= p["updated_at"]
    with pytest.raises(projects.ProjectError):
        projects.update(p["id"], name="")


def test_attach_and_detach_documents(isolated):
    (isolated / "a.pdf").write_bytes(b"x")
    p = projects.create("A")
    projects.attach_document(p["id"], "a.pdf")
    assert projects.attach_document(p["id"], "a.pdf")["documents"] == ["a.pdf"]
    assert projects.detach_document(p["id"], "a.pdf")["documents"] == []
    with pytest.raises(projects.ProjectError, match="not attached"):
        projects.detach_document(p["id"], "a.pdf")


def test_attach_rejects_missing_and_traversal(isolated, tmp_path):
    (tmp_path / "secret.pdf").write_bytes(b"x")
    p = projects.create("A")
    with pytest.raises(projects.ProjectError, match="No such uploaded"):
        projects.attach_document(p["id"], "missing.pdf")
    with pytest.raises(projects.ProjectError, match="Invalid filename"):
        projects.attach_document(p["id"], "../secret.pdf")


def test_add_conversation_is_idempotent():
    p = projects.create("A")
    projects.add_conversation(p["id"], "c1")
    assert projects.add_conversation(p["id"], "c1")["conversation_ids"] == ["c1"]


def test_add_link_validates_kind_and_dedupes():
    p = projects.create("A")
    projects.add_link(p["id"], "workflow", "j1", "research run")
    links = projects.add_link(p["id"], "workflow", "j1")["links"]
    assert len(links) == 1
    assert links[0]["title"] == "research run"
    assert links[0]["ts"]
    with pytest.raises(projects.ProjectError, match="Unknown link kind"):
        projects.add_link(p["id"], "coding", "j2")
    with pytest.raises(projects.ProjectError):
        projects.add_link(p["id"], "arena", " ")


def test_append_notes_adds_sections():
    p = projects.create("A")
    projects.append_notes(p["id"], "first finding")
    notes = projects.append_notes(p["id"], "second", heading="Council")["notes"]
    assert notes == "first finding\n\n## Council\n\nsecond\n"
    with pytest.raises(projects.ProjectError):
        projects.append_notes(p["id"], "  ")


def test_activate_deactivate_and_dangling_id():
    assert projects.active() is None
    p = projects.create("A")
    projects.activate(p["id"])
    assert projects.active()["id"] == p["id"]
    projects.deactivate()
    assert projects.active() is None
    projects.activate(p["id"])
    projects.delete(p["id"])
    assert settings.get("active_project") is None
    settings.update(active_project="gone")
    assert projects.active() is None
    assert settings.get("active_project") is None
    with pytest.raises(projects.ProjectError):
        projects.activate("gone")


def test_delete_keeps_space():
    p = projects.create("A")
    projects.delete(p["id"])
    assert spaces.get(p["space_id"])["name"] == "A"
    with pytest.raises(projects.ProjectError):
        projects.delete(p["id"])


# --- Chat integration ----------------------------------------------------------


def test_chat_context_without_project_is_default():
    ctx = projects_api.chat_context()
    assert ctx.doc_sources is None
    assert ctx.system_context is None
    projects_api.link_conversation("c1")  # no-op, no error


def test_chat_context_with_active_project(isolated):
    (isolated / "a.pdf").write_bytes(b"x")
    p = projects.create("Thesis", "Finish chapter 3")
    projects.attach_document(p["id"], "a.pdf")
    projects.update(p["id"], notes="Deadline Friday.")
    projects.activate(p["id"])

    ctx = projects_api.chat_context()
    assert ctx.doc_sources == ["a.pdf"]
    assert "Active project 'Thesis'" in ctx.system_context
    assert "Goal: Finish chapter 3" in ctx.system_context
    assert "Deadline Friday." in ctx.system_context

    projects_api.link_conversation("conv-1")
    assert projects.get(p["id"])["conversation_ids"] == ["conv-1"]


def test_system_context_is_sent_but_never_stored(monkeypatch):
    sent = []

    def fake_chat(messages, tools=None, model=None, options=None):
        sent.append(list(messages))
        return {"role": "assistant", "content": "ok", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    conversation = Conversation(system_prompt="base prompt")
    ctx = agent.RunContext(system_context="project notes here")

    assert agent.run("hi", conversation, model="m", context=ctx) == "ok"
    roles = [m["role"] for m in sent[0]]
    assert roles == ["system", "system", "user"]
    assert sent[0][1]["content"] == "project notes here"
    assert [m["role"] for m in conversation.messages] == ["system", "user", "assistant"]
    assert all(m.get("content") != "project notes here" for m in conversation.messages)


def test_system_context_goes_first_without_system_prompt(monkeypatch):
    sent = []

    def fake_chat(messages, tools=None, model=None, options=None):
        sent.append(list(messages))
        return {"role": "assistant", "content": "ok", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    conversation = Conversation()
    agent.run(
        "hi", conversation, model="m", context=agent.RunContext(system_context="x")
    )
    assert [m["role"] for m in sent[0]] == ["system", "user"]


def test_active_project_scopes_document_search(isolated, tmp_path, monkeypatch):
    """Real Chroma in a tmp path: with a project active, the chat context's
    doc_sources keeps search_documents from seeing unattached documents."""
    monkeypatch.setattr(config, "get_chroma_path", lambda: tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(
        ollama_client, "embed", lambda text, model=None: [1.0, 0.0, 0.0]
    )
    vectorstore.add(
        ids=["attached::0", "other::0"],
        embeddings=[[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        documents=["the attached fact", "the unattached fact"],
        metadatas=[{"source": "attached.pdf"}, {"source": "other.pdf"}],
    )
    (isolated / "attached.pdf").write_bytes(b"x")
    p = projects.create("A")
    projects.attach_document(p["id"], "attached.pdf")
    projects.activate(p["id"])

    ctx = projects_api.chat_context()
    out = agent._execute_tool("search_documents", {"query": "fact"}, ctx)
    assert "attached fact" in out
    assert "unattached fact" not in out

    projects.deactivate()
    out = agent._execute_tool(
        "search_documents", {"query": "fact"}, projects_api.chat_context()
    )
    assert "unattached fact" in out
    vectorstore._client = None
