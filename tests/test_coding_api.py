"""Contract tests for the coding-agent HTTP routes — mocked coding_agent/
runs/worktree, no live model or real git (that's tests/test_worktree.py and
tests/test_coding_agent.py's job; this file is only the HTTP contract, same
seam as the rest of tests/test_api.py)."""

from fastapi.testclient import TestClient

import coding_agent
import runs
import server
import worktree


def _client() -> TestClient:
    return TestClient(server.app)


def _fake_meta(**overrides) -> runs.RunMeta:
    base = dict(
        id="run1",
        repo_path="/workspace/repo",
        instruction="do x",
        model="qwen2.5",
        status="running",
        created_at="t0",
        updated_at="t0",
        steps=[],
        base_commit="abc123",
    )
    base.update(overrides)
    return runs.RunMeta(**base)


def test_create_coding_run_returns_meta(monkeypatch):
    monkeypatch.setattr(
        coding_agent, "start", lambda repo_path, instruction, model=None: _fake_meta()
    )
    resp = _client().post(
        "/api/coding/runs",
        json={"repo_path": "/workspace/repo", "instruction": "do x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "run1"
    assert body["status"] == "running"


def test_create_coding_run_rejects_path_outside_workspace(monkeypatch):
    def fake_start(repo_path, instruction, model=None):
        raise ValueError("outside workspace root")

    monkeypatch.setattr(coding_agent, "start", fake_start)
    resp = _client().post(
        "/api/coding/runs", json={"repo_path": "/", "instruction": "do x"}
    )
    assert resp.status_code == 400


def test_list_coding_runs(monkeypatch):
    monkeypatch.setattr(runs, "list_recent", lambda limit=20: [_fake_meta()])
    resp = _client().get("/api/coding/runs")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "run1"


def test_get_coding_run_includes_steps_and_diff(monkeypatch):
    meta = _fake_meta(
        status="awaiting_approval", steps=[{"type": "assistant", "content": "hi"}]
    )
    monkeypatch.setattr(runs, "load", lambda run_id: meta)
    monkeypatch.setattr(
        worktree, "diff", lambda run_id, base_commit: "diff --git a b\n"
    )

    resp = _client().get("/api/coding/runs/run1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["steps"] == [{"type": "assistant", "content": "hi"}]
    assert "diff --git" in body["diff"]


def test_get_coding_run_still_running_skips_diff_call(monkeypatch):
    """A running worktree's diff isn't fetched at all — avoids racing the
    background thread that's still writing to it."""
    meta = _fake_meta(status="running")
    monkeypatch.setattr(runs, "load", lambda run_id: meta)

    def boom(run_id, base_commit):
        raise AssertionError("worktree.diff should not be called while running")

    monkeypatch.setattr(worktree, "diff", boom)
    resp = _client().get("/api/coding/runs/run1")
    assert resp.status_code == 200
    assert resp.json()["diff"] == ""


def test_get_coding_run_missing_404s(monkeypatch):
    def fake_load(run_id):
        raise runs.RunError("nope")

    monkeypatch.setattr(runs, "load", fake_load)
    resp = _client().get("/api/coding/runs/does-not-exist")
    assert resp.status_code == 404


def test_apply_coding_run(monkeypatch):
    monkeypatch.setattr(
        coding_agent, "apply_run", lambda run_id: _fake_meta(status="applied")
    )
    resp = _client().post("/api/coding/runs/run1/apply")
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"


def test_apply_coding_run_wrong_status_400s(monkeypatch):
    def fake_apply(run_id):
        raise ValueError("not awaiting approval")

    monkeypatch.setattr(coding_agent, "apply_run", fake_apply)
    resp = _client().post("/api/coding/runs/run1/apply")
    assert resp.status_code == 400


def test_apply_coding_run_missing_404s(monkeypatch):
    def fake_apply(run_id):
        raise runs.RunError("nope")

    monkeypatch.setattr(coding_agent, "apply_run", fake_apply)
    resp = _client().post("/api/coding/runs/does-not-exist/apply")
    assert resp.status_code == 404


def test_discard_coding_run(monkeypatch):
    monkeypatch.setattr(
        coding_agent, "discard_run", lambda run_id: _fake_meta(status="discarded")
    )
    resp = _client().post("/api/coding/runs/run1/discard")
    assert resp.status_code == 200
    assert resp.json()["status"] == "discarded"


def test_discard_failed_coding_run_succeeds(monkeypatch):
    """A failed run's worktree is deliberately left around for inspection
    (coding_agent._run's except block) — discard is its cleanup path too."""
    monkeypatch.setattr(
        coding_agent, "discard_run", lambda run_id: _fake_meta(status="discarded")
    )
    resp = _client().post("/api/coding/runs/run1/discard")
    assert resp.status_code == 200


def test_get_failed_coding_run_still_returns_diff(monkeypatch):
    meta = _fake_meta(status="failed")
    monkeypatch.setattr(runs, "load", lambda run_id: meta)
    monkeypatch.setattr(
        worktree, "diff", lambda run_id, base_commit: "diff --git a b\n"
    )

    resp = _client().get("/api/coding/runs/run1")
    assert resp.status_code == 200
    assert "diff --git" in resp.json()["diff"]


def test_coding_run_events_streams_until_terminal(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda seconds: None)
    calls = {"n": 0}

    def fake_load(run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_meta(
                status="running", steps=[{"type": "assistant", "content": "a"}]
            )
        return _fake_meta(
            status="awaiting_approval",
            steps=[{"type": "assistant", "content": "a"}],
        )

    monkeypatch.setattr(runs, "load", fake_load)
    resp = _client().get("/api/coding/runs/run1/events")
    assert resp.status_code == 200
    assert '"content": "a"' in resp.text
    assert "awaiting_approval" in resp.text
