"""Coding-run registry — file-based store mirroring conversations.py.

Each run is a JSON file under runs/<id>.json:
{"id", "repo_path", "instruction", "model", "status", "created_at",
"updated_at", "steps", "base_commit"}. `status` moves
running -> awaiting_approval -> applied | discarded | failed.

Every model call, tool call + result, and test run is appended to `steps` as
it happens (plan.md Phase 16 decision 6) — a run is fully reconstructable
from this file afterward, not just a live stream that scrolls away. Written
from a background thread (coding_agent.py) while the API layer reads
concurrently (notably the /events SSE poller, every 0.3s during a run), so
writes are serialized with a lock AND made atomic via os.replace — the lock
orders concurrent writers, the atomic replace keeps lockless readers from
ever seeing a half-written file. runs/ is gitignored alongside
conversations/, uploads/, chroma/.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

RUNS_DIR = Path("runs")

_VALID_STATUSES = {"running", "awaiting_approval", "applied", "discarded", "failed"}

_lock = threading.Lock()


class RunError(Exception):
    """No such run on disk, or an invalid status value."""


@dataclass
class RunMeta:
    id: str
    repo_path: str
    instruction: str
    model: str
    status: str
    created_at: str
    updated_at: str
    steps: list[dict] = field(default_factory=list)
    base_commit: str = ""
    diff: str = ""


def _path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_raw(run_id: str) -> dict | None:
    path = _path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(record: dict) -> None:
    """Write atomically: a lockless reader (load/list_recent, and the
    /events SSE poller that reads the file every 0.3s while this thread
    writes on every step) must never observe a half-written file. Writing to
    a temp file and os.replace()-ing it into place is atomic on POSIX, so a
    reader always sees either the complete old file or the complete new one —
    no read-side lock needed."""
    RUNS_DIR.mkdir(exist_ok=True)
    path = _path(record["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)


def _meta(raw: dict) -> RunMeta:
    return RunMeta(
        id=raw["id"],
        repo_path=raw["repo_path"],
        instruction=raw["instruction"],
        model=raw["model"],
        status=raw["status"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        steps=raw["steps"],
        base_commit=raw["base_commit"],
        diff=raw.get("diff", ""),
    )


def create(
    repo_path: str, instruction: str, model: str, base_commit: str = ""
) -> RunMeta:
    """Create + persist a new run in `running` status. `base_commit` is
    normally known by the time the run starts (coding_agent.start reads the
    target repo's HEAD before creating the worktree) but defaults to empty
    for callers that don't have it yet."""
    with _lock:
        run_id = uuid4().hex[:12]
        now = _now()
        record = {
            "id": run_id,
            "repo_path": repo_path,
            "instruction": instruction,
            "model": model,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "steps": [],
            "base_commit": base_commit,
            "diff": "",
        }
        _write(record)
        return _meta(record)


def append_step(run_id: str, step: dict) -> None:
    """Append one ordered step (model turn, tool call + result, or test run)
    to the log. A "ts" timestamp is added if the caller didn't set one."""
    with _lock:
        raw = _read_raw(run_id)
        if raw is None:
            raise RunError(f"No such run: {run_id!r}")
        step = dict(step)
        step.setdefault("ts", _now())
        raw["steps"].append(step)
        raw["updated_at"] = _now()
        _write(raw)


def set_status(run_id: str, status: str) -> None:
    if status not in _VALID_STATUSES:
        raise RunError(
            f"Invalid status {status!r}; must be one of {sorted(_VALID_STATUSES)}."
        )
    with _lock:
        raw = _read_raw(run_id)
        if raw is None:
            raise RunError(f"No such run: {run_id!r}")
        raw["status"] = status
        raw["updated_at"] = _now()
        _write(raw)


def set_diff(run_id: str, diff: str) -> None:
    """Persist the run's final diff as an immutable artifact. Called at apply
    time, right before the worktree is torn down — after that the diff can no
    longer be recomputed (no worktree to diff), so it's frozen here and served
    from the record for terminal states instead of re-derived."""
    with _lock:
        raw = _read_raw(run_id)
        if raw is None:
            raise RunError(f"No such run: {run_id!r}")
        raw["diff"] = diff
        raw["updated_at"] = _now()
        _write(raw)


def load(run_id: str) -> RunMeta:
    raw = _read_raw(run_id)
    if raw is None:
        raise RunError(f"No such run: {run_id!r}")
    return _meta(raw)


def list_recent(limit: int = 20) -> list[RunMeta]:
    """The short history list, newest first."""
    if not RUNS_DIR.exists():
        return []
    metas = [_meta(json.loads(p.read_text())) for p in RUNS_DIR.glob("*.json")]
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas[:limit]


def delete(run_id: str) -> None:
    path = _path(run_id)
    if not path.exists():
        raise RunError(f"No such run: {run_id!r}")
    with _lock:
        path.unlink()
