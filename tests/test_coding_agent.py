"""Path-confinement tests for the coding agent's fs tools, plus a
walking-skeleton loop test against a mocked ollama_client driving a scripted
write_file -> run_tests -> finish sequence over a REAL git worktree (the
tools genuinely touch files/subprocesses; only the model call is mocked —
same seam test_agent.py uses for the chat loop)."""

import subprocess
from pathlib import Path

import pytest

import coding_agent
import ollama_client
import runs
import worktree

# --- Path confinement -------------------------------------------------------


def test_resolve_in_worktree_allows_nested_path(tmp_path):
    (tmp_path / "sub").mkdir()
    resolved = coding_agent._resolve_in_worktree(tmp_path, "sub/file.txt")
    assert resolved == (tmp_path / "sub" / "file.txt").resolve()


def test_resolve_in_worktree_rejects_dotdot_escape(tmp_path):
    with pytest.raises(coding_agent.PathEscapesWorktreeError):
        coding_agent._resolve_in_worktree(tmp_path, "../escaped.txt")


def test_resolve_in_worktree_rejects_absolute_path_outside_root(tmp_path):
    with pytest.raises(coding_agent.PathEscapesWorktreeError):
        coding_agent._resolve_in_worktree(tmp_path, "/etc/passwd")


def test_resolve_in_worktree_rejects_nested_dotdot_escape(tmp_path):
    (tmp_path / "sub").mkdir()
    with pytest.raises(coding_agent.PathEscapesWorktreeError):
        coding_agent._resolve_in_worktree(tmp_path, "sub/../../escaped.txt")


def test_write_file_rejects_path_outside_root(tmp_path):
    with pytest.raises(coding_agent.PathEscapesWorktreeError):
        coding_agent._write_file(tmp_path, "../../evil.txt", "pwned")


def test_read_file_rejects_path_outside_root(tmp_path):
    with pytest.raises(coding_agent.PathEscapesWorktreeError):
        coding_agent._read_file(tmp_path, "../../etc/passwd")


def test_read_file_missing_file_raises_clean_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        coding_agent._read_file(tmp_path, "nope.txt")


def test_write_then_read_round_trip(tmp_path):
    coding_agent._write_file(tmp_path, "sub/dir/new.txt", "hello")
    assert coding_agent._read_file(tmp_path, "sub/dir/new.txt") == "hello"


def test_list_files_excludes_git_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "a.py").write_text("x = 1\n")

    listing = coding_agent._list_files(tmp_path, None)
    assert "a.py" in listing
    assert ".git" not in listing


def test_execute_coding_tool_unknown_raises(tmp_path):
    with pytest.raises(ValueError):
        coding_agent._execute_coding_tool("nope", {}, tmp_path, "true")


# --- Loop, against a mocked ollama_client + a real worktree -----------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git("init", "-q", cwd=repo_path)
    _git("config", "user.email", "test@example.com", cwd=repo_path)
    _git("config", "user.name", "Test", cwd=repo_path)
    (repo_path / "README.md").write_text("hello\n")
    _git("add", "-A", cwd=repo_path)
    _git("commit", "-q", "-m", "initial", cwd=repo_path)

    monkeypatch.setattr(worktree, "_SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    return repo_path


def _script(monkeypatch, responses):
    state = {"n": 0}

    def fake_chat(messages, tools=None, model=None):
        resp = responses[min(state["n"], len(responses) - 1)]
        state["n"] += 1
        return resp

    monkeypatch.setattr(ollama_client, "chat", fake_chat)
    return state


def test_loop_drives_write_run_tests_finish(repo, monkeypatch):
    responses = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "write_file",
                        "arguments": {
                            "path": "module.py",
                            "content": '"""A new module."""\n',
                        },
                    }
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "run_tests", "arguments": {}}}],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "finish",
                        "arguments": {"summary": "Added module.py"},
                    }
                }
            ],
        },
    ]
    state = _script(monkeypatch, responses)

    base = worktree.head_commit(repo)
    meta = runs.create(str(repo), "add a module", "qwen2.5", base_commit=base)
    worktree.create(repo, meta.id, base)

    coding_agent._run(
        meta.id, worktree.worktree_path(meta.id), "add a module", "qwen2.5", "true"
    )

    assert state["n"] == 3

    reloaded = runs.load(meta.id)
    assert reloaded.status == "awaiting_approval"

    step_types = [s["type"] for s in reloaded.steps]
    # One "assistant" entry per model turn, one "tool_call" per tool call.
    assert step_types == [
        "assistant",
        "tool_call",
        "assistant",
        "tool_call",
        "assistant",
        "tool_call",
    ]

    tools_called = [s["tool"] for s in reloaded.steps if s["type"] == "tool_call"]
    assert tools_called == ["write_file", "run_tests", "finish"]

    run_tests_step = reloaded.steps[3]
    assert "exit_code=0" in run_tests_step["result"]

    finish_step = reloaded.steps[5]
    assert finish_step["result"] == "Added module.py"

    # The produced diff reflects the new file (via the untracked-file fix).
    patch = worktree.diff(meta.id, base)
    assert "module.py" in patch
    assert "A new module" in patch


def test_loop_stops_at_max_steps_without_finish(repo, monkeypatch):
    always_list = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "list_files", "arguments": {}}}],
    }
    state = _script(monkeypatch, [always_list])

    base = worktree.head_commit(repo)
    meta = runs.create(str(repo), "loop forever", "qwen2.5", base_commit=base)
    worktree.create(repo, meta.id, base)

    coding_agent._run(
        meta.id, worktree.worktree_path(meta.id), "loop forever", "qwen2.5", "true"
    )

    assert state["n"] == coding_agent.MAX_STEPS
    reloaded = runs.load(meta.id)
    assert reloaded.status == "awaiting_approval"
    assert "step limit" in reloaded.steps[-1]["content"]


def test_loop_marks_failed_on_unexpected_exception(repo, monkeypatch):
    def boom(messages, tools=None, model=None):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(ollama_client, "chat", boom)

    base = worktree.head_commit(repo)
    meta = runs.create(str(repo), "instr", "qwen2.5", base_commit=base)
    worktree.create(repo, meta.id, base)

    coding_agent._run(
        meta.id, worktree.worktree_path(meta.id), "instr", "qwen2.5", "true"
    )

    reloaded = runs.load(meta.id)
    assert reloaded.status == "failed"
    assert "network exploded" in reloaded.steps[-1]["content"]

    # The worktree is deliberately left in place on failure — a human may
    # need it to see what partial edits led to the failure — and is only
    # cleaned up via an explicit discard, same as awaiting_approval.
    assert worktree.worktree_path(meta.id).exists()
    discarded = coding_agent.discard_run(meta.id)
    assert discarded.status == "discarded"
    assert not worktree.worktree_path(meta.id).exists()


def test_apply_run_rejects_wrong_status(repo):
    base = worktree.head_commit(repo)
    meta = runs.create(str(repo), "instr", "qwen2.5", base_commit=base)
    worktree.create(repo, meta.id, base)
    runs.set_status(meta.id, "failed")

    with pytest.raises(ValueError):
        coding_agent.apply_run(meta.id)


def test_discard_run_rejects_status_that_isnt_pending_or_failed(repo):
    base = worktree.head_commit(repo)
    meta = runs.create(str(repo), "instr", "qwen2.5", base_commit=base)
    worktree.create(repo, meta.id, base)
    runs.set_status(meta.id, "applied")

    with pytest.raises(ValueError):
        coding_agent.discard_run(meta.id)


def test_start_rejects_repo_outside_workspace_root(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(
        config, "get_coding_workspace_root", lambda: tmp_path / "allowed"
    )
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    with pytest.raises(ValueError):
        coding_agent.start(str(outside), "do something")


def test_validate_repo_path_allows_nested_repo(tmp_path, monkeypatch):
    import config

    root = tmp_path / "workspace"
    nested = root / "myrepo"
    nested.mkdir(parents=True)
    monkeypatch.setattr(config, "get_coding_workspace_root", lambda: root)

    resolved = coding_agent._validate_repo_path(str(nested))
    assert resolved == nested.resolve()
