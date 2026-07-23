"""Worktree-wrapper tests against a REAL throwaway git repo in tmp_path —
git is fast and the whole point is real git behavior, not a mock (plan.md
Phase 16 test guidance)."""

import subprocess
from pathlib import Path

import pytest

import worktree


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo with one committed file."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git("init", "-q", cwd=repo_path)
    _git("config", "user.email", "test@example.com", cwd=repo_path)
    _git("config", "user.name", "Test", cwd=repo_path)
    (repo_path / "existing.txt").write_text("original\n")
    _git("add", "-A", cwd=repo_path)
    _git("commit", "-q", "-m", "initial commit", cwd=repo_path)

    # Keep worktrees out of the real system temp dir shared across test runs.
    monkeypatch.setattr(worktree, "_SCRATCH_ROOT", tmp_path / "scratch")
    return repo_path


def test_head_commit_returns_sha(repo):
    sha = worktree.head_commit(repo)
    assert len(sha) == 40


def test_head_commit_rejects_non_repo(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    with pytest.raises(worktree.WorktreeError):
        worktree.head_commit(not_a_repo)


def test_create_adds_worktree_and_branch(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)

    wt_path = worktree.worktree_path("run1")
    assert wt_path.is_dir()
    assert (wt_path / "existing.txt").read_text() == "original\n"

    branches = subprocess.run(
        ["git", "branch", "--list", worktree.branch_name("run1")],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert worktree.branch_name("run1") in branches


def test_diff_shows_modified_tracked_file(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)
    (worktree.worktree_path("run1") / "existing.txt").write_text("changed\n")

    patch = worktree.diff("run1", base)
    assert "-original" in patch
    assert "+changed" in patch


def test_diff_shows_new_untracked_file(repo):
    """git diff never shows untracked files regardless of the ref compared
    against — worktree.diff() must stage first or a brand-new file (very
    plausible for a real instruction) would silently produce an empty diff."""
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)
    (worktree.worktree_path("run1") / "new_module.py").write_text('"""New."""\n')

    patch = worktree.diff("run1", base)
    assert "new_module.py" in patch
    assert '"""New."""' in patch


def test_discard_leaves_repo_untouched_and_removes_worktree(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)
    (worktree.worktree_path("run1") / "existing.txt").write_text("changed\n")

    worktree.remove(repo, "run1")

    assert not worktree.worktree_path("run1").exists()
    assert (repo / "existing.txt").read_text() == "original\n"  # untouched
    branches = subprocess.run(
        ["git", "branch", "--list", worktree.branch_name("run1")],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert worktree.branch_name("run1") not in branches


def test_remove_tolerates_already_gone_worktree(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)
    worktree.remove(repo, "run1")

    worktree.remove(repo, "run1")  # should not raise


def test_apply_lands_diff_on_working_branch_including_new_files(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)
    wt_path = worktree.worktree_path("run1")
    (wt_path / "existing.txt").write_text("changed\n")
    (wt_path / "new_module.py").write_text('"""New."""\n')

    worktree.apply(repo, "run1", base)

    assert (repo / "existing.txt").read_text() == "changed\n"
    assert (repo / "new_module.py").read_text() == '"""New."""\n'
    assert not wt_path.exists()  # worktree cleaned up after apply

    # Applied as a plain working-tree change — nothing auto-committed.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "existing.txt" in status
    assert "new_module.py" in status


def test_apply_with_no_changes_is_a_noop_cleanup(repo):
    base = worktree.head_commit(repo)
    worktree.create(repo, "run1", base)

    worktree.apply(repo, "run1", base)  # nothing changed in the worktree

    assert (repo / "existing.txt").read_text() == "original\n"
    assert not worktree.worktree_path("run1").exists()
