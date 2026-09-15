"""agent.py Phase 19 seams: tool allowlist, options passthrough, RunContext
reaching the tools, and the new space/web dispatch cases (mocked)."""

import agent
import ollama_client
import spaces
from memory import Conversation
from tools import doc_search


def _names(schemas):
    return [s["function"]["name"] for s in schemas]


def test_available_tool_schemas_allowlist_and_web_flag(monkeypatch):
    everything = _names(agent.available_tool_schemas())
    assert {"web_search", "fetch_url", "read_space", "post_to_space"} <= set(everything)
    assert _names(agent.available_tool_schemas(["get_time", "nope"])) == ["get_time"]
    monkeypatch.setenv("ENABLE_WEB_TOOLS", "false")
    offline = _names(agent.available_tool_schemas())
    assert "web_search" not in offline and "fetch_url" not in offline
    assert "read_space" in offline


def test_run_passes_allowlist_and_options(monkeypatch):
    captured = {}

    def fake_chat(messages, tools=None, model=None, options=None):
        captured["tools"] = tools
        captured["options"] = options
        return {"role": "assistant", "content": "ok", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    conv = Conversation(system_prompt="sys")
    agent.run("hi", conv, tools=["get_time"], options={"temperature": 0})
    assert _names(captured["tools"]) == ["get_time"]
    assert captured["options"] == {"temperature": 0}


def test_context_doc_sources_reach_search(monkeypatch):
    seen = {}

    def fake_search(query, n_results=4, sources=None):
        seen["sources"] = sources
        return "hits"

    monkeypatch.setattr(doc_search, "search", fake_search)
    ctx = agent.RunContext(doc_sources=["a.pdf"])
    assert agent._execute_tool("search_documents", {"query": "q"}, ctx) == "hits"
    assert seen["sources"] == ["a.pdf"]
    agent._execute_tool("search_documents", {"query": "q"})
    assert seen["sources"] is None


def test_space_tools_use_agent_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    space = spaces.create("board")
    ctx = agent.RunContext(agent_name="critic @ llama")
    out = agent._execute_tool(
        "post_to_space", {"space_id": space["id"], "content": "Needs work."}, ctx
    )
    assert "critic @ llama" in out
    text = agent._execute_tool("read_space", {"space_id": space["id"]})
    assert "critic @ llama" in text and "Needs work." in text


def test_web_tools_dispatch(monkeypatch):
    from tools import web

    monkeypatch.setattr(web, "search", lambda q, n=5: f"searched {q} {n}")
    monkeypatch.setattr(web, "fetch", lambda url: f"fetched {url}")
    assert agent._execute_tool("web_search", {"query": "x", "max_results": 2}) == (
        "searched x 2"
    )
    assert agent._execute_tool("fetch_url", {"url": "https://a"}) == "fetched https://a"
