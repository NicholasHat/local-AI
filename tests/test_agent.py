"""Walking-skeleton test: the full tool-calling cycle against a mocked
ollama_client — no live model."""

import agent
import ollama_client
from memory import Conversation


def _script(monkeypatch, responses):
    """Replace ollama_client.chat with a scripted fake. Records the messages
    sent on each call; returns the last scripted response once exhausted."""
    state = {"n": 0, "sent": []}

    def fake_chat(messages, tools=None, model=None):
        state["sent"].append(list(messages))
        resp = responses[min(state["n"], len(responses) - 1)]
        state["n"] += 1
        return resp

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    return state


def test_tool_call_round_trip(monkeypatch):
    responses = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}],
        },
        {"role": "assistant", "content": "It is done.", "tool_calls": None},
    ]
    state = _script(monkeypatch, responses)

    conv = Conversation()
    reply = agent.run("what time is it?", conv)

    assert reply == "It is done."
    assert state["n"] == 2  # one tool round, then the final answer

    roles = [m["role"] for m in conv.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]

    tool_msg = conv.messages[2]
    assert tool_msg["tool_name"] == "get_time"
    assert "T" in tool_msg["content"]  # ISO timestamp actually executed

    # The tools schema was advertised to the model.
    assert conv.messages[1]["tool_calls"][0]["function"]["name"] == "get_time"


def test_max_iteration_guard(monkeypatch):
    always_tool = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}],
    }
    state = _script(monkeypatch, [always_tool])

    conv = Conversation()
    reply = agent.run("loop forever", conv)

    assert state["n"] == agent.MAX_ITERATIONS  # stopped, did not run away
    assert "tool-call limit" in reply


def test_unknown_tool_error_fed_back(monkeypatch):
    responses = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "nope", "arguments": {}}}],
        },
        {"role": "assistant", "content": "recovered", "tool_calls": None},
    ]
    _script(monkeypatch, responses)

    conv = Conversation()
    reply = agent.run("call a bad tool", conv)

    assert reply == "recovered"
    assert "Error executing nope" in conv.messages[2]["content"]


def test_execute_tool_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        agent._execute_tool("does_not_exist", {})


def test_run_default_model_is_none(monkeypatch):
    captured = {}

    def fake_chat(messages, tools=None, model=None):
        captured["model"] = model
        return {"role": "assistant", "content": "done", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    agent.run("hi", Conversation())
    assert captured["model"] is None


def test_run_passes_explicit_model_to_chat(monkeypatch):
    captured = {}

    def fake_chat(messages, tools=None, model=None):
        captured["model"] = model
        return {"role": "assistant", "content": "done", "tool_calls": None}

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    agent.run("hi", Conversation(), model="llama3.1")
    assert captured["model"] == "llama3.1"
