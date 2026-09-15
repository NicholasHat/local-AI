"""Shared communication spaces — the substrate for model-to-model
communication (plan.md decision 3, Phases 19–26).

A space is a persisted, append-only board: spaces/<id>.json holding
{"id", "name", "purpose", "created_at", "updated_at", "posts"} where each
post is {"id", "ts", "author", "content"}. Any agent reads it and posts to
it through two ordinary chat tools (agent.py: read_space / post_to_space),
so several models — in a workflow, or in separate chats — converse through
the same board, and a human can read it live or post into it from the
Spaces page. Nothing here knows what a "model" is: authors are just names.

Same file/lock/atomic-replace discipline as runs.py and jobstore.py — a
workflow's parallel steps post concurrently while the UI polls.
"""

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SPACES_DIR = Path("spaces")
_MAX_RENDERED_POSTS = 200
# Ids are uuid4 hex prefixes. Validated here, at the point of filesystem
# access, because the read_space / post_to_space tools pass a
# model-controlled id straight through — and the chat model reads untrusted
# documents and web pages.
_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")

_lock = threading.Lock()


class SpaceError(Exception):
    """No such space, or an invalid post."""


@dataclass
class SpaceMeta:
    id: str
    name: str
    purpose: str
    created_at: str
    updated_at: str
    post_count: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path(space_id: str) -> Path:
    if not _ID_PATTERN.match(space_id or ""):
        raise SpaceError(f"Invalid space id: {space_id!r}")
    return SPACES_DIR / f"{space_id}.json"


def _read_raw(space_id: str) -> dict | None:
    path = _path(space_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(record: dict) -> None:
    SPACES_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(record["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)


def _meta(raw: dict) -> SpaceMeta:
    return SpaceMeta(
        id=raw["id"],
        name=raw["name"],
        purpose=raw["purpose"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        post_count=len(raw["posts"]),
    )


def create(name: str, purpose: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise SpaceError("A space needs a name.")
    with _lock:
        now = _now()
        record = {
            "id": uuid4().hex[:12],
            "name": name,
            "purpose": purpose.strip(),
            "created_at": now,
            "updated_at": now,
            "posts": [],
        }
        _write(record)
        return record


def get(space_id: str) -> dict:
    """The full record, posts included (oldest first)."""
    raw = _read_raw(space_id)
    if raw is None:
        raise SpaceError(f"No such space: {space_id!r}")
    return raw


def get_meta(space_id: str) -> SpaceMeta:
    return _meta(get(space_id))


def post(space_id: str, author: str, content: str) -> dict:
    author = (author or "").strip()
    content = (content or "").strip()
    if not author:
        raise SpaceError("A post needs an author.")
    if not content:
        raise SpaceError("A post needs content.")
    with _lock:
        raw = _read_raw(space_id)
        if raw is None:
            raise SpaceError(f"No such space: {space_id!r}")
        entry = {
            "id": uuid4().hex[:12],
            "ts": _now(),
            "author": author,
            "content": content,
        }
        raw["posts"].append(entry)
        raw["updated_at"] = entry["ts"]
        _write(raw)
        return entry


def list_recent(limit: int = 50) -> list[SpaceMeta]:
    """Newest-activity first."""
    if not SPACES_DIR.exists():
        return []
    metas = [_meta(json.loads(p.read_text())) for p in SPACES_DIR.glob("*.json")]
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas[:limit]


def delete(space_id: str) -> None:
    path = _path(space_id)
    if not path.exists():
        raise SpaceError(f"No such space: {space_id!r}")
    with _lock:
        path.unlink()


def render(space_id: str, limit: int = 30) -> str:
    """The last `limit` posts as plain text for a model to read — the shape
    the read_space tool returns."""
    raw = get(space_id)
    limit = max(1, min(int(limit or 30), _MAX_RENDERED_POSTS))
    posts = raw["posts"][-limit:]
    header = f"Space '{raw['name']}' ({raw['id']})"
    if raw["purpose"]:
        header += f" — purpose: {raw['purpose']}"
    if not posts:
        return f"{header}\n(no posts yet)"
    lines = [header, f"Showing the last {len(posts)} of {len(raw['posts'])} posts:", ""]
    for p in posts:
        lines.append(f"[{p['ts'][:19]}] {p['author']}:\n{p['content']}\n")
    return "\n".join(lines).rstrip()
