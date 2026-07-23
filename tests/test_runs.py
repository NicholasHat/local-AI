"""Unit tests for the coding-run registry — create/append/load/list/status/
delete, JSON round-tripping. No live model, no git needed here (worktree.py
has its own tests against a real repo)."""

import pytest

import runs


@pytest.fixture(autouse=True)
def isolated_runs_dir(tmp_path, monkeypatch):
    """Every test gets its own throwaway runs/ dir — never touch the
    project's real one."""
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def test_create_persists_running_run_with_base_commit():
    meta = runs.create("repo", "add a docstring", "qwen2.5", base_commit="abc123")
    assert meta.status == "running"
    assert meta.repo_path == "repo"
    assert meta.instruction == "add a docstring"
    assert meta.model == "qwen2.5"
    assert meta.base_commit == "abc123"
    assert meta.steps == []

    reloaded = runs.load(meta.id)
    assert reloaded == meta


def test_create_defaults_base_commit_to_empty_string():
    meta = runs.create("repo", "instr", "qwen2.5")
    assert meta.base_commit == ""


def test_append_step_accumulates_in_order():
    meta = runs.create("repo", "instr", "qwen2.5")
    runs.append_step(meta.id, {"type": "assistant", "content": "thinking"})
    runs.append_step(meta.id, {"type": "tool_call", "tool": "write_file"})

    reloaded = runs.load(meta.id)
    assert [s["type"] for s in reloaded.steps] == ["assistant", "tool_call"]
    assert all("ts" in s for s in reloaded.steps)  # timestamp auto-filled


def test_append_step_keeps_explicit_timestamp():
    meta = runs.create("repo", "instr", "qwen2.5")
    runs.append_step(meta.id, {"type": "assistant", "ts": "explicit"})
    assert runs.load(meta.id).steps[0]["ts"] == "explicit"


def test_append_step_missing_run_raises():
    with pytest.raises(runs.RunError):
        runs.append_step("does-not-exist", {"type": "assistant"})


def test_set_status_transitions():
    meta = runs.create("repo", "instr", "qwen2.5")
    runs.set_status(meta.id, "awaiting_approval")
    assert runs.load(meta.id).status == "awaiting_approval"

    runs.set_status(meta.id, "applied")
    assert runs.load(meta.id).status == "applied"


def test_set_status_rejects_invalid_value():
    meta = runs.create("repo", "instr", "qwen2.5")
    with pytest.raises(runs.RunError):
        runs.set_status(meta.id, "not-a-real-status")


def test_set_status_missing_run_raises():
    with pytest.raises(runs.RunError):
        runs.set_status("does-not-exist", "failed")


def test_load_missing_run_raises():
    with pytest.raises(runs.RunError):
        runs.load("does-not-exist")


def test_list_recent_sorted_newest_first():
    meta1 = runs.create("repo", "instr1", "qwen2.5")
    meta2 = runs.create("repo", "instr2", "qwen2.5")
    # Bump meta1's updated_at past meta2's.
    runs.append_step(meta1.id, {"type": "assistant"})

    ids = [m.id for m in runs.list_recent()]
    assert ids[0] == meta1.id
    assert meta2.id in ids


def test_list_recent_respects_limit():
    for i in range(5):
        runs.create("repo", f"instr{i}", "qwen2.5")
    assert len(runs.list_recent(limit=2)) == 2


def test_list_recent_empty_when_no_runs_dir():
    assert runs.list_recent() == []


def test_delete_removes_run():
    meta = runs.create("repo", "instr", "qwen2.5")
    runs.delete(meta.id)
    with pytest.raises(runs.RunError):
        runs.load(meta.id)


def test_delete_missing_run_raises():
    with pytest.raises(runs.RunError):
        runs.delete("does-not-exist")
