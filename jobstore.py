"""Generic background-job store — one primitive for every long-running
thing added in Phases 19+ (benchmarks, arena comparisons, workflow runs).

A job is a JSON file under jobs/<kind>/<id>.json:
{"id", "kind", "status", "created_at", "updated_at", "payload", "events",
 "result", "error"}. `status` moves running -> succeeded | failed.

`payload` is the job's input (what was asked), `events` is the ordered,
append-as-it-happens log (what the job did), `result` is the final output
(what came of it). The same concurrency discipline as runs.py applies: a
background thread writes while the API's SSE poller reads, so writes are
serialized with a lock AND made atomic via os.replace so a lockless reader
never sees a half-written file. runs.py is deliberately NOT refactored onto
this — it works and carries coding-specific fields (plan.md decision 1 for
Phases 19–26).
"""

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

JOBS_DIR = Path("jobs")

_VALID_STATUSES = {"running", "succeeded", "failed"}
_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_lock = threading.Lock()


class JobError(Exception):
    """No such job on disk, or an invalid kind/status value."""


@dataclass
class Job:
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    payload: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "payload": self.payload,
            "events": self.events,
            "result": self.result,
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_kind(kind: str) -> None:
    if not _KIND_PATTERN.match(kind):
        raise JobError(f"Invalid job kind {kind!r}.")


def _path(kind: str, job_id: str) -> Path:
    _validate_kind(kind)
    return JOBS_DIR / kind / f"{job_id}.json"


def _read_raw(kind: str, job_id: str) -> dict | None:
    path = _path(kind, job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(record: dict) -> None:
    path = _path(record["kind"], record["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record))
    os.replace(tmp, path)


def _job(raw: dict) -> Job:
    return Job(**raw)


def _mutate(kind: str, job_id: str, fn) -> None:
    with _lock:
        raw = _read_raw(kind, job_id)
        if raw is None:
            raise JobError(f"No such {kind} job: {job_id!r}")
        fn(raw)
        raw["updated_at"] = _now()
        _write(raw)


def create(kind: str, payload: dict) -> Job:
    _validate_kind(kind)
    with _lock:
        now = _now()
        record = {
            "id": uuid4().hex[:12],
            "kind": kind,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "payload": payload,
            "events": [],
            "result": None,
            "error": None,
        }
        _write(record)
        return _job(record)


def append_event(kind: str, job_id: str, event: dict) -> None:
    """Append one ordered event; a "ts" timestamp is added if absent."""
    event = dict(event)
    event.setdefault("ts", _now())
    _mutate(kind, job_id, lambda raw: raw["events"].append(event))


def set_status(kind: str, job_id: str, status: str) -> None:
    if status not in _VALID_STATUSES:
        raise JobError(
            f"Invalid status {status!r}; must be one of {sorted(_VALID_STATUSES)}."
        )
    _mutate(kind, job_id, lambda raw: raw.__setitem__("status", status))


def succeed(kind: str, job_id: str, result: dict) -> None:
    """Store the final result and mark the job succeeded, atomically."""

    def apply(raw):
        raw["result"] = result
        raw["status"] = "succeeded"

    _mutate(kind, job_id, apply)


def fail(kind: str, job_id: str, error: str) -> None:
    def apply(raw):
        raw["error"] = error
        raw["status"] = "failed"

    _mutate(kind, job_id, apply)


def load(kind: str, job_id: str) -> Job:
    raw = _read_raw(kind, job_id)
    if raw is None:
        raise JobError(f"No such {kind} job: {job_id!r}")
    return _job(raw)


def list_recent(kind: str, limit: int = 20) -> list[Job]:
    """Newest first."""
    _validate_kind(kind)
    directory = JOBS_DIR / kind
    if not directory.exists():
        return []
    jobs = [_job(json.loads(p.read_text())) for p in directory.glob("*.json")]
    jobs.sort(key=lambda j: j.updated_at, reverse=True)
    return jobs[:limit]


def delete(kind: str, job_id: str) -> None:
    path = _path(kind, job_id)
    if not path.exists():
        raise JobError(f"No such {kind} job: {job_id!r}")
    with _lock:
        path.unlink()


def run_in_background(kind: str, payload: dict, fn) -> Job:
    """Create a job and run `fn(job_id)` on a daemon thread. `fn` returns the
    result dict (stored via succeed()); any exception it raises becomes the
    job's error (via fail()). This is the one place the running -> terminal
    transition is driven, so every job kind fails loudly, never hangs in
    `running`."""
    job = create(kind, payload)

    def target():
        try:
            result = fn(job.id)
            succeed(kind, job.id, result if result is not None else {})
        except Exception as exc:  # any failure must land in the record
            try:
                fail(kind, job.id, f"{type(exc).__name__}: {exc}")
            except JobError:
                # The record was deleted while the job ran (the UI allows
                # it); there is nowhere left to report to, and a daemon
                # thread dying with a traceback helps no one.
                pass

    threading.Thread(target=target, daemon=True, name=f"{kind}-{job.id}").start()
    return job
