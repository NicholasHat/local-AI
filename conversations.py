"""Conversation registry — persisted, multi-conversation history (Phase 14).

Each conversation is a JSON file under conversations/<id>.json:
{"id", "title", "created_at", "updated_at", "messages"}. File-based, like
skills.py, rather than a database — a handful of small, human-readable
records, no new dependency. conversations/ is gitignored alongside
uploads/ and chroma/.

Title is derived once from the first user message and never changes after —
no extra model call to summarize it.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from memory import Conversation

CONVERSATIONS_DIR = Path("conversations")
_TITLE_MAX_LEN = 40
_UNTITLED = "New chat"


class ConversationError(Exception):
    """No such conversation on disk."""


@dataclass
class ConversationMeta:
    id: str
    title: str
    created_at: str
    updated_at: str


def _path(conversation_id: str) -> Path:
    return CONVERSATIONS_DIR / f"{conversation_id}.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _derive_title(messages: list[dict]) -> str:
    first_user = next((m for m in messages if m["role"] == "user"), None)
    if first_user is None:
        return _UNTITLED
    text = (first_user.get("content") or "").strip().replace("\n", " ")
    if not text:
        return _UNTITLED
    return text[:_TITLE_MAX_LEN] + ("…" if len(text) > _TITLE_MAX_LEN else "")


def _read_raw(conversation_id: str) -> dict | None:
    path = _path(conversation_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(
    conversation_id: str, *, title: str, created_at: str, messages: list[dict]
) -> None:
    CONVERSATIONS_DIR.mkdir(exist_ok=True)
    record = {
        "id": conversation_id,
        "title": title,
        "created_at": created_at,
        "updated_at": _now(),
        "messages": messages,
    }
    _path(conversation_id).write_text(json.dumps(record))


def create(system_prompt: str | None = None) -> tuple[str, Conversation]:
    """Create + persist a brand-new, empty conversation. Returns (id, Conversation)."""
    conversation_id = uuid4().hex[:12]
    conversation = Conversation(system_prompt=system_prompt)
    now = _now()
    _write(
        conversation_id,
        title=_UNTITLED,
        created_at=now,
        messages=conversation.messages,
    )
    return conversation_id, conversation


def save(conversation_id: str, conversation: Conversation) -> None:
    """Persist the current message list. Keeps the existing title once it's
    been set from the first user message; re-derives it until then."""
    existing = _read_raw(conversation_id)
    if existing is None:
        raise ConversationError(f"No such conversation: {conversation_id!r}")

    messages = conversation.messages
    title = existing["title"]
    if title == _UNTITLED:
        title = _derive_title(messages)
    _write(
        conversation_id,
        title=title,
        created_at=existing["created_at"],
        messages=messages,
    )


def load(conversation_id: str) -> Conversation:
    """Reconstruct a memory.Conversation from its persisted messages."""
    raw = _read_raw(conversation_id)
    if raw is None:
        raise ConversationError(f"No such conversation: {conversation_id!r}")
    return Conversation.from_messages(raw["messages"])


def get_meta(conversation_id: str) -> ConversationMeta | None:
    raw = _read_raw(conversation_id)
    if raw is None:
        return None
    return ConversationMeta(
        id=raw["id"],
        title=raw["title"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


def list_recent(limit: int = 20) -> list[ConversationMeta]:
    """The short history list, newest first."""
    if not CONVERSATIONS_DIR.exists():
        return []
    metas = [get_meta(path.stem) for path in CONVERSATIONS_DIR.glob("*.json")]
    metas = [m for m in metas if m is not None]
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas[:limit]


def delete(conversation_id: str) -> None:
    path = _path(conversation_id)
    if not path.exists():
        raise ConversationError(f"No such conversation: {conversation_id!r}")
    path.unlink()
