"""Unit tests for the conversation registry — create/list/load/save/delete,
JSON round-tripping, and title derivation. No live model needed."""

import pytest

import conversations
from memory import Conversation


@pytest.fixture(autouse=True)
def isolated_conversations_dir(tmp_path, monkeypatch):
    """Every test gets its own throwaway conversations/ dir — never touch
    the project's real one."""
    monkeypatch.setattr(conversations, "CONVERSATIONS_DIR", tmp_path / "conversations")
    return tmp_path / "conversations"


def test_create_persists_empty_conversation_with_system_prompt():
    conversation_id, conversation = conversations.create(system_prompt="be helpful")
    assert conversation.messages == [{"role": "system", "content": "be helpful"}]

    meta = conversations.get_meta(conversation_id)
    assert meta.title == "New chat"
    assert meta.id == conversation_id


def test_load_reconstructs_persisted_messages():
    conversation_id, conversation = conversations.create(system_prompt="be helpful")
    conversation.add_user("hello")
    conversations.save(conversation_id, conversation)

    reloaded = conversations.load(conversation_id)
    assert reloaded.messages == conversation.messages


def test_load_missing_conversation_raises():
    with pytest.raises(conversations.ConversationError):
        conversations.load("does-not-exist")


def test_save_derives_title_from_first_user_message():
    conversation_id, conversation = conversations.create()
    conversation.add_user("What's the capital of France?")
    conversations.save(conversation_id, conversation)

    title = conversations.get_meta(conversation_id).title
    assert title == "What's the capital of France?"


def test_save_truncates_long_title():
    conversation_id, conversation = conversations.create()
    conversation.add_user("x" * 100)
    conversations.save(conversation_id, conversation)

    title = conversations.get_meta(conversation_id).title
    assert len(title) == 41  # 40 chars + ellipsis
    assert title.endswith("…")


def test_save_title_is_sticky_once_set():
    conversation_id, conversation = conversations.create()
    conversation.add_user("first message")
    conversations.save(conversation_id, conversation)

    conversation.add_user("second message")
    conversations.save(conversation_id, conversation)

    assert conversations.get_meta(conversation_id).title == "first message"


def test_save_missing_conversation_raises():
    with pytest.raises(conversations.ConversationError):
        conversations.save("does-not-exist", Conversation())


def test_list_recent_sorted_newest_first():
    id1, _ = conversations.create()
    id2, conversation2 = conversations.create()
    # Re-saving id2 bumps its updated_at past id1's.
    conversation2.add_user("hi")
    conversations.save(id2, conversation2)

    ids = [m.id for m in conversations.list_recent()]
    assert ids[0] == id2
    assert id1 in ids


def test_list_recent_respects_limit():
    for _ in range(5):
        conversations.create()
    assert len(conversations.list_recent(limit=2)) == 2


def test_list_recent_empty_when_no_conversations_dir():
    assert conversations.list_recent() == []


def test_delete_removes_conversation():
    conversation_id, _ = conversations.create()
    conversations.delete(conversation_id)
    assert conversations.get_meta(conversation_id) is None


def test_delete_missing_conversation_raises():
    with pytest.raises(conversations.ConversationError):
        conversations.delete("does-not-exist")


def test_get_meta_missing_returns_none():
    assert conversations.get_meta("does-not-exist") is None
