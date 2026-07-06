"""Tests for the Conversation store."""

from memory import Conversation


def test_system_prompt_seeds_first_message():
    conv = Conversation(system_prompt="you are helpful")
    assert conv.messages[0] == {"role": "system", "content": "you are helpful"}


def test_add_user_and_tool_result_shapes():
    conv = Conversation()
    conv.add_user("hi")
    conv.add_tool_result("get_time", 123)  # non-str coerced
    assert conv.messages[0] == {"role": "user", "content": "hi"}
    assert conv.messages[1] == {
        "role": "tool",
        "tool_name": "get_time",
        "content": "123",
    }


def test_add_assistant_strips_none_fields():
    conv = Conversation()
    conv.add_assistant(
        {"content": "hello", "thinking": None, "images": None, "tool_calls": None}
    )
    assert conv.messages[0] == {"role": "assistant", "content": "hello"}


def test_add_assistant_keeps_tool_calls():
    calls = [{"function": {"name": "get_time", "arguments": {}}}]
    conv = Conversation()
    conv.add_assistant({"content": "", "tool_calls": calls})
    assert conv.messages[0]["tool_calls"] == calls


def test_messages_returns_a_copy():
    conv = Conversation()
    conv.add_user("hi")
    conv.messages.append({"role": "user", "content": "mutation"})
    assert len(conv.messages) == 1  # external mutation didn't leak in
