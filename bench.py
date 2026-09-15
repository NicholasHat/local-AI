"""Benchmarks + arena (plan.md decision 5, Phases 19–26) — the measurements
behind "which local model is strongest for what".

Benchmark: benchmarks/suite.yaml is a small local eval suite whose every
task has a deterministic checker (contains / regex / number / json /
tool_called), so scores are reproducible offline with no LLM judge. A run
scores one model on every task, records speed from the response metrics
ollama_client.chat_stats() exposes, and writes one file per model to
bench_results/ — the leaderboard is just those files. Tool tasks go through
agent.run() with a tool allowlist and a fresh Conversation, so a "did it
call the tool" check reads the real transcript; coding tasks never execute
model output.

Arena: the ad-hoc comparison — one prompt, N models concurrently, side by
side with timing, plus an optional judge model whose reasoned 1–10 verdict
is the thing the user actually wants to read. Answers are shown to the
judge anonymously (A/B/C) and mapped back, so the judge can't favour a name.

Both run as jobstore jobs (kinds "bench" and "arena"): events stream while
they run, the result is stored when they finish.

leaderboard() -> list[dict], one row per benchmarked model:
    {"model": "qwen2.5:latest",
     "tool_capable": True,
     "overall": 0.0..1.0,               # mean over all suite tasks
     "categories": {"reasoning": 0..1, "coding": 0..1, "instruction": 0..1,
                    "tools": 0..1, "json": 0..1, "knowledge": 0..1},
     "tokens_per_sec": float | None,    # eval tokens / eval seconds
     "load_seconds": float | None,
     "ran_at": "<iso timestamp>",
     "suite_version": "<benchmarks/suite.yaml version>"}
"""

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

import agent
import jobstore
import ollama_client
import providers
from memory import Conversation

SUITE_PATH = Path("benchmarks/suite.yaml")
RESULTS_DIR = Path("bench_results")

BENCH_KIND = "bench"
ARENA_KIND = "arena"

CHECK_TYPES = ("contains", "regex", "number", "json", "tool_called")
_ANSWER_EXCERPT_CHARS = 400
_ARENA_MAX_MODELS = 8

_BENCH_SYSTEM_PROMPT = (
    "You are being evaluated. Answer concisely and follow the requested "
    "answer format exactly."
)


class BenchError(Exception):
    """Malformed suite, unknown model result, or invalid arena request."""


# --- Suite ---------------------------------------------------------------------


def load_suite() -> dict:
    """{"version": int, "tasks": [...]} — validated so a bad task fails
    loudly here, not halfway through a run."""
    if not SUITE_PATH.exists():
        raise BenchError(f"No suite at {SUITE_PATH}")
    data = yaml.safe_load(SUITE_PATH.read_text()) or {}
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        raise BenchError("Suite has no tasks.")
    seen = set()
    for task in tasks:
        for key in ("id", "category", "prompt", "check"):
            if key not in task:
                raise BenchError(f"Task {task.get('id')!r} is missing {key!r}.")
        if task["id"] in seen:
            raise BenchError(f"Duplicate task id {task['id']!r}.")
        seen.add(task["id"])
        check_type = task["check"].get("type")
        if check_type not in CHECK_TYPES:
            raise BenchError(
                f"Task {task['id']!r} has unknown check type {check_type!r}."
            )
    return {"version": data.get("version", 0), "tasks": tasks}


# --- Checkers -----------------------------------------------------------------

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_fence(text: str) -> str:
    match = _FENCE_PATTERN.search(text)
    return match.group(1).strip() if match else text.strip()


def _parse_json_object(text: str) -> dict | None:
    candidate = _strip_fence(text)
    for attempt in (candidate, _extract_braces(candidate)):
        if not attempt:
            continue
        try:
            parsed = json.loads(attempt)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_braces(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else ""


def check_answer(check: dict, answer: str) -> bool:
    """Mechanically score an answer against a task's `check` (module docstring
    / suite.yaml header for the shapes). tool_called is scored separately
    from the transcript (see _run_tool_task)."""
    kind = check["type"]
    text = answer or ""
    if kind == "contains":
        lowered = text.lower()
        return any(str(option).lower() in lowered for option in check["any"])
    if kind == "regex":
        return re.search(check["pattern"], text.strip(), re.IGNORECASE) is not None
    if kind == "number":
        numbers = _NUMBER_PATTERN.findall(text.replace(",", ""))
        if not numbers:
            return False
        return abs(float(numbers[-1]) - float(check["value"])) <= float(
            check.get("tol", 0)
        )
    if kind == "json":
        parsed = _parse_json_object(text)
        return parsed is not None and all(k in parsed for k in check["keys"])
    raise BenchError(f"Unknown check type {kind!r}.")


def expected_text(check: dict) -> str:
    """A short human-readable description of what the check wanted."""
    kind = check["type"]
    if kind == "contains":
        return "contains: " + " | ".join(str(o) for o in check["any"])
    if kind == "regex":
        return f"matches /{check['pattern']}/"
    if kind == "number":
        return f"= {check['value']}" + (f" ±{check['tol']}" if check.get("tol") else "")
    if kind == "json":
        return "JSON with keys " + ", ".join(check["keys"])
    if kind == "tool_called":
        return f"calls {check['tool']}"
    return kind


# --- Stats ----------------------------------------------------------------------


def _speed(stats: dict) -> dict:
    """tokens_per_sec + load_seconds from Ollama's nanosecond metrics."""
    eval_count = stats.get("eval_count") or 0
    eval_duration = stats.get("eval_duration") or 0
    load_duration = stats.get("load_duration")
    return {
        "tokens_per_sec": (eval_count / (eval_duration / 1e9))
        if eval_count and eval_duration
        else None,
        "eval_count": eval_count or None,
        "eval_seconds": (eval_duration / 1e9) if eval_duration else None,
        "load_seconds": (load_duration / 1e9) if load_duration is not None else None,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# --- Benchmark run ------------------------------------------------------------


def _run_plain_task(task: dict, model: str, options: dict | None) -> tuple:
    """Non-tool task: one system + user message, no tools. Returns
    (passed, answer, stats)."""
    messages = [
        {"role": "system", "content": _BENCH_SYSTEM_PROMPT},
        {"role": "user", "content": task["prompt"]},
    ]
    response = ollama_client.chat_stats(messages, model=model, options=options)
    answer = response["message"].get("content") or ""
    return check_answer(task["check"], answer), answer, response["stats"]


def _run_tool_task(task: dict, model: str, options: dict | None) -> tuple:
    """tool_called task: through the real agent loop with an allowlist, then
    read the transcript for a tool-role message from the wanted tool."""
    check = task["check"]
    conversation = Conversation(system_prompt=_BENCH_SYSTEM_PROMPT)
    answer = agent.run(
        task["prompt"],
        conversation,
        model=model,
        tools=list(check.get("tools") or [check["tool"]]),
        options=options,
    )
    called = any(
        m.get("role") == "tool" and m.get("tool_name") == check["tool"]
        for m in conversation.messages
    )
    return called, answer, {}


def _safe_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", model)


def _result_path(model: str) -> Path:
    return RESULTS_DIR / f"{_safe_name(model)}.json"


def run_suite(
    model: str, job_id: str | None = None, options: dict | None = None
) -> dict:
    """Score `model` on every suite task; write bench_results/<model>.json and
    return its content (the leaderboard row plus per-task details). With a
    job_id, one jobstore event per task streams progress."""
    suite = load_suite()
    installed = {m["name"]: m for m in ollama_client.list_models()}
    tool_capable = "tools" in installed.get(model, {}).get("capabilities", [])

    task_results = []
    for task in suite["tasks"]:
        is_tool_task = task["check"]["type"] == "tool_called"
        started = time.perf_counter()
        error = None
        try:
            runner = _run_tool_task if is_tool_task else _run_plain_task
            passed, answer, stats = runner(task, model, options)
        except Exception as exc:  # a broken task must not sink the whole run
            passed, answer, stats, error = False, "", {}, f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - started
        speed = _speed(stats)
        entry = {
            "type": "task",
            "id": task["id"],
            "category": task["category"],
            "passed": passed,
            "seconds": round(seconds, 3),
            "tokens_per_sec": speed["tokens_per_sec"],
            "eval_count": speed["eval_count"],
            "eval_seconds": speed["eval_seconds"],
            "load_seconds": speed["load_seconds"],
            "answer": answer[:_ANSWER_EXCERPT_CHARS],
            "expected": expected_text(task["check"]),
        }
        if error:
            entry["error"] = error
        task_results.append(entry)
        if job_id:
            jobstore.append_event(BENCH_KIND, job_id, entry)

    by_category: dict[str, list[bool]] = {}
    for entry in task_results:
        by_category.setdefault(entry["category"], []).append(entry["passed"])
    total_tokens = sum(e["eval_count"] or 0 for e in task_results)
    total_eval_seconds = sum(e["eval_seconds"] or 0 for e in task_results)
    record = {
        "model": model,
        "tool_capable": tool_capable,
        "overall": sum(e["passed"] for e in task_results) / len(task_results),
        "categories": {cat: sum(v) / len(v) for cat, v in sorted(by_category.items())},
        # Total tokens over total eval time, not a mean of per-task rates: a
        # 3-token answer's rate is dominated by fixed overhead and would
        # drag the average far below the model's real throughput.
        "tokens_per_sec": (total_tokens / total_eval_seconds)
        if total_tokens and total_eval_seconds
        else None,
        "load_seconds": _mean(
            [e["load_seconds"] for e in task_results if e["load_seconds"] is not None]
        ),
        "ran_at": datetime.now(UTC).isoformat(),
        "suite_version": suite["version"],
        "tasks": task_results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # leaderboard() globs and parses this directory while runs write into
    # it, so land the file atomically.
    path = _result_path(model)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2))
    os.replace(tmp, path)
    return record


def start(model: str, options: dict | None = None) -> jobstore.Job:
    """Run the suite on a background thread (kind "bench")."""
    if not model:
        raise BenchError("A model is required.")
    payload = {"model": model, "options": options or {}}
    return jobstore.run_in_background(
        BENCH_KIND, payload, lambda job_id: run_suite(model, job_id, options)
    )


_ROW_KEYS = (
    "model",
    "tool_capable",
    "overall",
    "categories",
    "tokens_per_sec",
    "load_seconds",
    "ran_at",
    "suite_version",
)


def _row(record: dict) -> dict:
    return {key: record.get(key) for key in _ROW_KEYS}


def leaderboard() -> list[dict]:
    """One fixed-shape row per benchmarked model, best overall first."""
    if not RESULTS_DIR.exists():
        return []
    rows = [_row(json.loads(p.read_text())) for p in RESULTS_DIR.glob("*.json")]
    rows.sort(key=lambda r: (r["overall"] or 0, r["tokens_per_sec"] or 0), reverse=True)
    return rows


def result(model: str) -> dict:
    """The full stored result (row + per-task details) for one model."""
    path = _result_path(model)
    if not path.exists():
        raise BenchError(f"No benchmark result for {model!r}.")
    return json.loads(path.read_text())


# --- Arena --------------------------------------------------------------------

_LETTERS = "ABCDEFGH"

_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial judge comparing answers from anonymous assistants "
    "to the same prompt. Score each answer from 1 (useless) to 10 (excellent) "
    "for correctness, completeness, and clarity. Respond with ONLY a JSON "
    'object mapping each answer letter to {"score": <1-10>, "rationale": '
    '"<one or two sentences>"}. No other text.'
)


def _judge_prompt(prompt: str, answers: list[dict]) -> str:
    parts = [f"PROMPT:\n{prompt}\n"]
    for letter, answer in zip(_LETTERS, answers, strict=False):
        content = answer.get("content") or f"(no answer: {answer.get('error')})"
        parts.append(f"ANSWER {letter}:\n{content}\n")
    parts.append(
        "Return JSON like "
        + json.dumps(
            {
                letter: {"score": 7, "rationale": "..."}
                for letter, _ in zip(_LETTERS, answers, strict=False)
            }
        )
    )
    return "\n".join(parts)


def parse_verdicts(raw: str, models: list[str]) -> list[dict]:
    """Map the judge's A/B/C JSON back to model names. Tolerates fences,
    stray text around the object, and letter keys in either case; anything
    unparseable becomes an "unparsed" verdict carrying the raw text rather
    than failing the arena."""
    parsed = _parse_json_object(raw) or {}
    normalized = {str(k).strip().upper(): v for k, v in parsed.items()}
    verdicts = []
    for letter, model in zip(_LETTERS, models, strict=False):
        entry = normalized.get(letter)
        if entry is None:
            entry = normalized.get(f"ANSWER {letter}")
        score, rationale = None, None
        if isinstance(entry, dict):
            try:
                score = int(round(float(entry.get("score"))))
                score = max(1, min(10, score))
            except (TypeError, ValueError):
                score = None
            rationale = str(entry.get("rationale") or "").strip() or None
        elif isinstance(entry, int | float):
            score = max(1, min(10, int(round(entry))))
        verdict = {
            "type": "verdict",
            "model": model,
            "score": score,
            "rationale": rationale,
        }
        if score is None:
            verdict["unparsed"] = raw[: _ANSWER_EXCERPT_CHARS * 2]
        verdicts.append(verdict)
    return verdicts


def _answer_one(prompt: str, model: str, options: dict | None) -> dict:
    started = time.perf_counter()
    entry: dict = {"type": "answer", "model": model, "content": "", "stats": {}}
    try:
        response = ollama_client.chat_stats(
            [{"role": "user", "content": prompt}], model=model, options=options
        )
        entry["content"] = response["message"].get("content") or ""
        entry["stats"] = _speed(response["stats"])
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
    entry["stats"]["seconds"] = round(time.perf_counter() - started, 3)
    return entry


def run_arena(
    prompt: str,
    models: list[str],
    judge: str | None,
    job_id: str | None = None,
    options: dict | None = None,
) -> dict:
    """Every model answers concurrently; the judge (if any) scores them
    anonymously. Returns {prompt, judge, answers, verdicts}."""
    answers: list[dict | None] = [None] * len(models)

    def worker(index: int, model: str) -> None:
        answers[index] = _answer_one(prompt, model, options)
        if job_id:
            jobstore.append_event(ARENA_KIND, job_id, answers[index])

    threads = [
        threading.Thread(target=worker, args=(i, m), daemon=True)
        for i, m in enumerate(models)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    done = [a for a in answers if a is not None]

    verdicts: list[dict] = []
    if judge:
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _judge_prompt(prompt, done)},
        ]
        response = ollama_client.chat_stats(
            messages, model=judge, options={"temperature": 0}
        )
        raw = response["message"].get("content") or ""
        verdicts = parse_verdicts(raw, models)
        if job_id:
            for verdict in verdicts:
                jobstore.append_event(ARENA_KIND, job_id, verdict)
    return {"prompt": prompt, "judge": judge, "answers": done, "verdicts": verdicts}


def start_arena(
    prompt: str,
    models: list[str],
    judge: str | None = None,
    options: dict | None = None,
) -> jobstore.Job:
    """Start an arena comparison on a background thread (kind "arena").
    judge "auto" resolves to the active provider's judge route."""
    prompt = (prompt or "").strip()
    models = [m for m in dict.fromkeys(models or []) if m]
    if not prompt:
        raise BenchError("A prompt is required.")
    if len(models) < 2:
        raise BenchError("Pick at least two distinct models to compare.")
    if len(models) > _ARENA_MAX_MODELS:
        raise BenchError(f"At most {_ARENA_MAX_MODELS} models per arena.")
    if judge == "auto":
        judge = providers.resolve("judge")
    payload = {
        "prompt": prompt,
        "models": models,
        "judge": judge,
        "options": options or {},
    }
    return jobstore.run_in_background(
        ARENA_KIND,
        payload,
        lambda job_id: run_arena(prompt, models, judge, job_id, options),
    )
