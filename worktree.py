"""Git worktree lifecycle for the sandboxed coding agent (Phase 16).

The worktree *is* the sandbox, the diff, and the undo (plan.md Phase 16
decision 2) — `git worktree add` gives a disposable checkout on a scratch
branch off a captured base commit; the agent only ever touches files there.
`git diff` against that base commit is the review artifact, for free.
Discarding is `git worktree remove` + deleting the scratch branch — the
target repo's own working tree and branches are never touched until an
explicit apply. No custom snapshotting; git already solved this.

Thin subprocess wrappers only, same spirit as ollama_client.py's thin-wrapper
rule for Ollama traffic — no retry/business logic here, just git plumbing
with errors surfaced as WorktreeError instead of silent failures.
"""

import subprocess
import tempfile
from pathlib import Path

BRANCH_PREFIX = "coding-agent"

_SCRATCH_ROOT = Path(tempfile.gettempdir()) / "local-ai-coding-runs"


class WorktreeError(Exception):
    """A git command failed, or repo_path isn't a usable git repository."""


def branch_name(run_id: str) -> str:
    return f"{BRANCH_PREFIX}/{run_id}"


def worktree_path(run_id: str) -> Path:
    """Deterministic scratch location, keyed only by run_id — kept outside
    the target repo's own tree so it never shows up in the repo's own `git
    status`, and out of any allowlisted workspace root so it can't be
    mistaken for a real project directory."""
    return _SCRATCH_ROOT / run_id


def _git(
    *args: str, cwd: Path, input: str | None = None
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, input=input
    )
    if result.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def head_commit(repo_path: Path) -> str:
    """The commit the worktree will be based on. Also doubles as the
    "is this actually a git repo" check — raises WorktreeError otherwise."""
    try:
        return _git("rev-parse", "HEAD", cwd=repo_path).stdout.strip()
    except FileNotFoundError as exc:  # repo_path doesn't exist at all
        raise WorktreeError(f"Not a directory: {repo_path}") from exc


def create(repo_path: Path, run_id: str, base_commit: str) -> None:
    """Create the scratch branch + worktree at base_commit."""
    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    _git(
        "worktree",
        "add",
        "-b",
        branch_name(run_id),
        str(worktree_path(run_id)),
        base_commit,
        cwd=repo_path,
    )


def diff(run_id: str, base_commit: str) -> str:
    """Unified diff of everything changed in the worktree since base_commit,
    including new (untracked) files. `git diff` alone never shows untracked
    files regardless of the ref compared against — that's how the plumbing
    command works, not a special case — so untracked paths are staged first.
    Staging is harmless here: nothing is ever committed, and the worktree is
    torn down (or applied) right after review."""
    wt_path = worktree_path(run_id)
    _git("add", "-A", cwd=wt_path)
    return _git("diff", "--cached", base_commit, cwd=wt_path).stdout


def apply(repo_path: Path, run_id: str, base_commit: str) -> None:
    """Land the run's diff onto repo_path's currently checked-out branch as
    a plain uncommitted change — the human reviews/commits it themselves,
    nothing auto-merges — then clean up the worktree and scratch branch."""
    patch = diff(run_id, base_commit)
    if patch.strip():
        _git("apply", cwd=repo_path, input=patch)
    remove(repo_path, run_id)


def remove(repo_path: Path, run_id: str) -> None:
    """git worktree remove --force + delete the scratch branch. Tolerates
    the worktree already being gone (e.g. a repeat discard)."""
    wt_path = worktree_path(run_id)
    if wt_path.exists():
        _git("worktree", "remove", "--force", str(wt_path), cwd=repo_path)
    subprocess.run(
        ["git", "branch", "-D", branch_name(run_id)],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
