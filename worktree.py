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


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _show(repo_path: Path, commit: str, rel: str) -> str:
    """The content of `rel` at `commit`, or '' if it didn't exist there (a
    file the run newly created has no ancestor version)."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{rel}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def _merge3(ours: str, base: str, theirs: str) -> tuple[str, bool]:
    """A 3-way content merge via `git merge-file` — git's own merge engine.
    Returns (merged text, clean): clean is False only when the two sides edit
    the SAME region. Touches nothing on disk outside a temp dir, so a conflict
    can be reported without ever writing markers into the real working tree."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "ours").write_text(ours)
        (d / "base").write_text(base)
        (d / "theirs").write_text(theirs)
        merge_file = ["git", "merge-file", "-p"]
        merge_file += [str(d / "ours"), str(d / "base"), str(d / "theirs")]
        result = subprocess.run(merge_file, capture_output=True, text=True)
    # merge-file's exit code is the conflict count (0 = clean, >0 = conflicts).
    return result.stdout, result.returncode == 0


def apply(repo_path: Path, run_id: str, base_commit: str) -> None:
    """Merge the run's changes into repo_path's working tree as uncommitted
    edits — the human reviews/commits them, nothing auto-commits — then tear
    down the worktree.

    Uses a real per-file 3-way merge (base = the file at base_commit, theirs =
    the run's version, ours = the working tree's current version) rather than
    `git apply`, which refuses on ANY context drift. This makes approving
    succeed even when the working tree moved on since the run started — an
    earlier approved run that left uncommitted edits, or the user's own
    changes. Only genuinely OVERLAPPING edits conflict; every merge is
    computed first and the working tree is written only if all are clean, so a
    conflict aborts with a clear error and leaves the tree exactly as it was
    (no half-applied state, no conflict markers)."""
    wt = worktree_path(run_id)
    _git("add", "-A", cwd=wt)  # so run-created (untracked) files show in the list
    names = _git("diff", "--name-only", base_commit, cwd=wt).stdout.split()

    merged: dict[str, str] = {}
    conflicts: list[str] = []
    for rel in names:
        result, clean = _merge3(
            ours=_read(repo_path / rel),
            base=_show(repo_path, base_commit, rel),
            theirs=_read(wt / rel),
        )
        if clean:
            merged[rel] = result
        else:
            conflicts.append(rel)

    if conflicts:
        raise WorktreeError(
            "the repository changed since this run started, conflicting with "
            f"this run's edits to {', '.join(conflicts)}. Discard this run and "
            "start a new one against the current state of the repo."
        )

    for rel, content in merged.items():
        target = repo_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

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
