"""The sandboxed coding agent — a bounded loop, sibling to agent.py.

Loop shape mirrors agent.py exactly (send history -> model returns
tool_calls? -> _execute_coding_tool() each -> append results -> repeat ->
until finish()/no tool_calls -> stop), bounded by MAX_STEPS the same way
agent.py is bounded by MAX_ITERATIONS. Every Ollama call still goes through
ollama_client.chat (the thin-wrapper rule holds).

This is deliberately a SEPARATE loop and dispatch from agent.py's
_execute_tool, not a new case added there (plan.md Phase 16 decision 3): the
tools here can write files and run a subprocess, so they must be
unreachable from the general chat agent, which reads untrusted documents
and search results. There is no "start a coding run" tool anywhere in
agent.py's schema — a run is only ever started by an explicit human action
via the API (decision 4).

Every model turn, tool call + args + result, and status transition is
appended to the run log (runs.py) as it happens, so a run is fully
reconstructable afterward — not just a live stream that scrolls away
(decision 6). start() runs the loop on a background thread so the API's
`/events` SSE route (server.py) has something live to poll while the model
is still working; apply_run/discard_run/get_diff operate on the persisted
run + the worktree independently of that thread.
"""

import shlex
import subprocess
import threading
from pathlib import Path

import config
import ollama_client
import runs
import worktree

MAX_STEPS = 12
_MAX_OUTPUT_CHARS = 4000

SYSTEM_PROMPT = (
    "You are a sandboxed coding agent. You are working inside an isolated "
    "git worktree checked out from a real repository — you may list, read, "
    "and write files ONLY within it, and run the project's test command. "
    "Nothing you do here touches the real branch; a human reviews your diff "
    "and explicitly approves or discards it afterward, so it is safe to "
    "make the change and check your own work. Make the smallest change that "
    "satisfies the instruction. Run the tests to check your work before "
    "finishing when the repo has a way to run them. Call finish(summary) "
    "exactly once you are done (or once you've concluded no change is "
    "needed), summarizing what you changed and why."
)


# --- Tools -----------------------------------------------------------------


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in the worktree, optionally filtered by a glob "
                "pattern (e.g. '**/*.py'). Defaults to every file."
            ),
            "parameters": _obj(
                {
                    "glob": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '**/*.py'. Optional.",
                    }
                },
                [],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's full text content from the worktree.",
            "parameters": _obj(
                {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the worktree root.",
                    }
                },
                ["path"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write (create or overwrite) a file in the worktree with the "
                "given content. Creates parent directories as needed."
            ),
            "parameters": _obj(
                {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the worktree root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full new content of the file.",
                    },
                },
                ["path", "content"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run this repo's configured test command in the worktree and "
                "return its exit code and (truncated) stdout/stderr. Takes no "
                "arguments — you choose WHEN to test, the command itself is "
                "fixed by the repo's configuration."
            ),
            "parameters": _obj({}, []),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Call this exactly once you are done making changes (or once "
                "you've concluded no change is needed), to end the run "
                "cleanly and hand the diff to the human for review."
            ),
            "parameters": _obj(
                {
                    "summary": {
                        "type": "string",
                        "description": "What you changed and why (or why not).",
                    }
                },
                ["summary"],
            ),
        },
    },
]


class PathEscapesWorktreeError(ValueError):
    """A tool tried to touch a path outside the worktree root."""


def _resolve_in_worktree(root: Path, rel_path: str) -> Path:
    """Path-confinement guard: resolve, then check parent containment — the
    same discipline as server.py's delete_document, never a bare string/
    `.name` compare (a literal '..' segment survives that check)."""
    root_resolved = root.resolve()
    candidate = (root_resolved / rel_path).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathEscapesWorktreeError(
            f"Path {rel_path!r} resolves outside the worktree root."
        )
    return candidate


def _list_files(root: Path, glob: str | None) -> str:
    root_resolved = root.resolve()
    pattern = glob or "**/*"
    paths = sorted(
        p.relative_to(root_resolved).as_posix()
        for p in root_resolved.glob(pattern)
        if p.is_file() and ".git" not in p.relative_to(root_resolved).parts
    )
    return "\n".join(paths) if paths else "(no files match)"


def _read_file(root: Path, path: str) -> str:
    target = _resolve_in_worktree(root, path)
    if not target.is_file():
        raise FileNotFoundError(f"No such file: {path!r}")
    return target.read_text()


def _write_file(root: Path, path: str, content: str) -> str:
    target = _resolve_in_worktree(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Wrote {path!r} ({len(content)} bytes)."


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text)} chars total]"


def _run_tests(root: Path, command: str) -> str:
    """Run the CONFIGURED command (never a model-chosen one) as a subprocess
    in the worktree. The model decides when to call this, not what it runs."""
    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return f"Command {command!r} timed out after 300s."
    return (
        f"exit_code={result.returncode}\n"
        f"--- stdout ---\n{_truncate(result.stdout)}\n"
        f"--- stderr ---\n{_truncate(result.stderr)}"
    )


def _execute_coding_tool(
    name: str, args: dict, worktree_root: Path, test_command: str
) -> str:
    """The single dispatch point for the coding agent's tools — its own,
    separate from agent.py's _execute_tool (see module docstring)."""
    if name == "list_files":
        return _list_files(worktree_root, args.get("glob"))
    if name == "read_file":
        return _read_file(worktree_root, args["path"])
    if name == "write_file":
        return _write_file(worktree_root, args["path"], args["content"])
    if name == "run_tests":
        return _run_tests(worktree_root, test_command)
    if name == "finish":
        return args.get("summary", "")
    raise ValueError(f"Unknown coding tool: {name!r}")


# --- Repo path confinement --------------------------------------------------


def _validate_repo_path(repo_path: str) -> Path:
    root = config.get_coding_workspace_root()
    resolved = Path(repo_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(
            f"{repo_path!r} is outside the allowed coding workspace root "
            f"({root}). Set CODING_WORKSPACE_ROOT to change it."
        )
    return resolved


# --- Loop --------------------------------------------------------------


def _run(
    run_id: str,
    worktree_root: Path,
    instruction: str,
    model: str,
    test_command: str,
) -> None:
    """Run the bounded loop to completion, persisting every step to
    runs.py, and set a terminal status (awaiting_approval or failed)."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    try:
        for _ in range(MAX_STEPS):
            message = ollama_client.chat(
                messages=messages, tools=TOOL_SCHEMAS, model=model
            )
            clean = {k: v for k, v in message.items() if v is not None}
            clean["role"] = "assistant"
            messages.append(clean)
            runs.append_step(
                run_id,
                {
                    "type": "assistant",
                    "model": model,
                    "content": message.get("content", ""),
                    "tool_calls": message.get("tool_calls"),
                },
            )

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                runs.append_step(
                    run_id,
                    {
                        "type": "stopped",
                        "model": model,
                        "content": (
                            "Model returned no tool calls without calling finish()."
                        ),
                    },
                )
                runs.set_status(run_id, "awaiting_approval")
                return

            for call in tool_calls:
                fn = call["function"]
                name = fn["name"]
                args = fn.get("arguments") or {}
                try:
                    result = _execute_coding_tool(
                        name, args, worktree_root, test_command
                    )
                except Exception as exc:  # feed errors back so the model can recover
                    result = f"Error executing {name}: {exc}"
                messages.append(
                    {"role": "tool", "tool_name": name, "content": str(result)}
                )
                runs.append_step(
                    run_id,
                    {
                        "type": "tool_call",
                        "model": model,
                        "tool": name,
                        "args": args,
                        "result": str(result),
                    },
                )
                if name == "finish":
                    runs.set_status(run_id, "awaiting_approval")
                    return

        runs.append_step(
            run_id,
            {
                "type": "stopped",
                "model": model,
                "content": (
                    f"Stopped after reaching the step limit (MAX_STEPS={MAX_STEPS}) "
                    "without finish()."
                ),
            },
        )
        runs.set_status(run_id, "awaiting_approval")
    except Exception as exc:
        # Deliberately does NOT remove the worktree here — a failed run's
        # diff (whatever partial edits exist) may be exactly what a human
        # needs to debug why it failed. discard_run() is the cleanup path
        # for both `awaiting_approval` and `failed`, so the worktree is
        # reachable until a human explicitly discards it.
        runs.append_step(run_id, {"type": "error", "model": model, "content": str(exc)})
        runs.set_status(run_id, "failed")


def start(repo_path: str, instruction: str, model: str | None = None) -> runs.RunMeta:
    """Validate repo_path, create the worktree, and kick off the loop on a
    background thread. Returns immediately with the new run's metadata so
    the API isn't blocked for the whole run — server.py's /events route
    polls runs.load() for the live step log while status == 'running'."""
    resolved_repo = _validate_repo_path(repo_path)
    resolved_model = model or config.get_model()
    base_commit = worktree.head_commit(resolved_repo)

    meta = runs.create(
        repo_path=str(resolved_repo),
        instruction=instruction,
        model=resolved_model,
        base_commit=base_commit,
    )
    worktree.create(resolved_repo, meta.id, base_commit)

    thread = threading.Thread(
        target=_run,
        args=(
            meta.id,
            worktree.worktree_path(meta.id),
            instruction,
            resolved_model,
            config.get_coding_test_command(),
        ),
        daemon=True,
    )
    thread.start()
    return meta


def get_diff(run_id: str) -> str:
    """The run's diff, sourced correctly for its state — the single place that
    knows where a run's diff lives:

    - `applied`: the worktree is gone (apply tore it down), so serve the diff
      frozen into the record at apply time (runs.set_diff).
    - `awaiting_approval` / `failed`: the worktree still exists — compute live.
      `failed` keeps its worktree on purpose (see _run's except block).
    - `running` / `discarded`: nothing meaningful to show.

    The live path is guarded broadly: a missing worktree degrades to an empty
    diff rather than escaping as an error (worktree.diff runs git in the
    worktree's cwd, which raises a bare FileNotFoundError — an OSError, not a
    WorktreeError — if that directory is gone)."""
    meta = runs.load(run_id)
    if meta.status == "applied":
        return meta.diff
    if meta.status not in {"awaiting_approval", "failed"}:
        return ""
    try:
        return worktree.diff(run_id, meta.base_commit)
    except (worktree.WorktreeError, OSError):
        return ""


def apply_run(run_id: str) -> runs.RunMeta:
    meta = runs.load(run_id)
    if meta.status != "awaiting_approval":
        raise ValueError(
            f"Run {run_id!r} is not awaiting approval (status={meta.status!r})."
        )
    # Freeze the diff before applying — worktree.apply removes the worktree as
    # its last step, and once it's gone the diff can't be recomputed. Storing
    # it here keeps the applied change visible in the run history (the audit
    # log, decision 6) instead of it vanishing with the worktree.
    runs.set_diff(run_id, worktree.diff(run_id, meta.base_commit))
    worktree.apply(Path(meta.repo_path), run_id, meta.base_commit)
    runs.set_status(run_id, "applied")
    return runs.load(run_id)


def discard_run(run_id: str) -> runs.RunMeta:
    """Also the cleanup path for a `failed` run: `_run`'s exception handler
    deliberately does NOT remove the worktree itself — a failed run's diff
    may be exactly what a human needs to debug why it failed, so the worktree
    is left in place for inspection until a human explicitly discards it
    (same one-human-decision pattern as every other terminal state)."""
    meta = runs.load(run_id)
    if meta.status not in {"awaiting_approval", "failed"}:
        raise ValueError(
            f"Run {run_id!r} cannot be discarded (status={meta.status!r})."
        )
    worktree.remove(Path(meta.repo_path), run_id)
    runs.set_status(run_id, "discarded")
    return runs.load(run_id)
