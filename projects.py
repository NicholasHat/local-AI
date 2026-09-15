"""Projects — a goal, notes, and links that group work (plan.md decision 8,
Phases 19–26). Projects group; they don't fork the store.

projects/<id>.json:
{"id", "name", "goal", "notes", "documents": [uploaded filenames],
 "conversation_ids": [...], "links": [{"kind", "id", "title", "ts"}],
 "space_id", "created_at", "updated_at"}

Documents stay in the one Chroma collection: an active project only
*filters* search_documents to its attached filenames and lends its goal +
notes to the chat's system context (api/projects.py.chat_context). Each
project gets its own shared space at creation — a durable transcript that
outlives the project record (delete() leaves the space alone).

Same lock + atomic os.replace discipline as spaces.py.
"""

import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import config
import settings
import spaces

PROJECTS_DIR = Path("projects")
LINK_KINDS = ("workflow", "arena", "bench")

_lock = threading.Lock()


class ProjectError(Exception):
    """No such project, or an invalid name/document/link."""


@dataclass
class ProjectMeta:
    id: str
    name: str
    goal: str
    created_at: str
    updated_at: str
    document_count: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{project_id}.json"


def _read_raw(project_id: str) -> dict | None:
    path = _path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(record: dict) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(record["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)


def _mutate(project_id: str, fn) -> dict:
    with _lock:
        raw = _read_raw(project_id)
        if raw is None:
            raise ProjectError(f"No such project: {project_id!r}")
        fn(raw)
        raw["updated_at"] = _now()
        _write(raw)
        return raw


def _meta(raw: dict) -> ProjectMeta:
    return ProjectMeta(
        id=raw["id"],
        name=raw["name"],
        goal=raw["goal"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        document_count=len(raw["documents"]),
    )


def create(name: str, goal: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ProjectError("A project needs a name.")
    goal = (goal or "").strip()
    space = spaces.create(name, purpose=goal)
    with _lock:
        now = _now()
        record = {
            "id": uuid4().hex[:12],
            "name": name,
            "goal": goal,
            "notes": "",
            "documents": [],
            "conversation_ids": [],
            "links": [],
            "space_id": space["id"],
            "created_at": now,
            "updated_at": now,
        }
        _write(record)
        return record


def get(project_id: str) -> dict:
    raw = _read_raw(project_id)
    if raw is None:
        raise ProjectError(f"No such project: {project_id!r}")
    return raw


def list_recent(limit: int = 50) -> list[ProjectMeta]:
    """Newest-activity first."""
    if not PROJECTS_DIR.exists():
        return []
    metas = [_meta(json.loads(p.read_text())) for p in PROJECTS_DIR.glob("*.json")]
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas[:limit]


def update(
    project_id: str,
    name: str | None = None,
    goal: str | None = None,
    notes: str | None = None,
) -> dict:
    if name is not None and not name.strip():
        raise ProjectError("A project needs a name.")

    def apply(raw):
        if name is not None:
            raw["name"] = name.strip()
        if goal is not None:
            raw["goal"] = goal.strip()
        if notes is not None:
            raw["notes"] = notes

    return _mutate(project_id, apply)


def delete(project_id: str) -> None:
    """Remove the record. Its space is kept — it's a transcript."""
    path = _path(project_id)
    if not path.exists():
        raise ProjectError(f"No such project: {project_id!r}")
    with _lock:
        path.unlink()
    if settings.get("active_project") == project_id:
        settings.update(active_project=None)


def _validate_uploaded(filename: str) -> str:
    """Path-traversal-safe via resolved-path containment (the same check as
    server.py's delete_document): the file must be directly inside the
    upload dir and exist there."""
    upload_dir = config.get_upload_dir()
    path = (upload_dir / filename).resolve()
    if path.parent != upload_dir.resolve():
        raise ProjectError("Invalid filename.")
    if not path.is_file():
        raise ProjectError(f"No such uploaded document: {filename!r}")
    return path.name


def attach_document(project_id: str, filename: str) -> dict:
    safe = _validate_uploaded(filename)

    def apply(raw):
        if safe not in raw["documents"]:
            raw["documents"].append(safe)

    return _mutate(project_id, apply)


def detach_document(project_id: str, filename: str) -> dict:
    def apply(raw):
        if filename not in raw["documents"]:
            raise ProjectError(f"Document {filename!r} is not attached.")
        raw["documents"].remove(filename)

    return _mutate(project_id, apply)


def add_conversation(project_id: str, conversation_id: str) -> dict:
    def apply(raw):
        if conversation_id not in raw["conversation_ids"]:
            raw["conversation_ids"].append(conversation_id)

    return _mutate(project_id, apply)


def add_link(project_id: str, kind: str, job_id: str, title: str = "") -> dict:
    if kind not in LINK_KINDS:
        raise ProjectError(f"Unknown link kind {kind!r}; kinds are {LINK_KINDS}.")
    if not (job_id or "").strip():
        raise ProjectError("A link needs an id.")

    def apply(raw):
        if any(link["kind"] == kind and link["id"] == job_id for link in raw["links"]):
            return
        raw["links"].append(
            {"kind": kind, "id": job_id, "title": title.strip(), "ts": _now()}
        )

    return _mutate(project_id, apply)


def append_notes(project_id: str, text: str, heading: str | None = None) -> dict:
    """Append `text` to the notes as a new section — how a workflow/arena
    output gets saved into the project."""
    text = (text or "").strip()
    if not text:
        raise ProjectError("Nothing to append.")

    def apply(raw):
        block = (
            f"## {heading.strip()}\n\n{text}" if heading and heading.strip() else text
        )
        raw["notes"] = (
            f"{raw['notes'].rstrip()}\n\n{block}\n"
            if raw["notes"].strip()
            else f"{block}\n"
        )

    return _mutate(project_id, apply)


def active() -> dict | None:
    """The active project, or None. A dangling id (project deleted from
    disk) is cleared rather than raised."""
    project_id = settings.get("active_project")
    if not project_id:
        return None
    raw = _read_raw(project_id)
    if raw is None:
        settings.update(active_project=None)
        return None
    return raw


def activate(project_id: str) -> dict:
    raw = get(project_id)
    settings.update(active_project=project_id)
    return raw


def deactivate() -> None:
    settings.update(active_project=None)
