"""Unit tests for bench.py — checkers, the suite runner, the leaderboard,
and the arena, all against a mocked ollama_client / agent. No live model."""

import json
import time

import pytest

import agent
import bench
import jobstore
import ollama_client


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "RESULTS_DIR", tmp_path / "bench_results")
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(
        ollama_client,
        "list_models",
        lambda: [
            {"name": "m-tools", "size": 1, "digest": None, "capabilities": ["tools"]},
            {"name": "m-plain", "size": 1, "digest": None, "capabilities": []},
        ],
    )


def _stats(eval_count=10, eval_ns=1_000_000_000, load_ns=500_000_000):
    return {
        "eval_count": eval_count,
        "eval_duration": eval_ns,
        "load_duration": load_ns,
        "prompt_eval_count": 5,
        "prompt_eval_duration": 1,
        "total_duration": 2,
        "done_reason": "stop",
    }


def _reply(content, stats=None):
    return {
        "message": {"role": "assistant", "content": content},
        "stats": stats or _stats(),
    }


# --- Suite + checkers ----------------------------------------------------------


def test_suite_loads_with_valid_tasks_in_every_category():
    suite = bench.load_suite()
    assert suite["version"] == 1
    categories = {t["category"] for t in suite["tasks"]}
    assert categories == {
        "reasoning",
        "coding",
        "instruction",
        "tools",
        "json",
        "knowledge",
    }
    assert all(t["check"]["type"] in bench.CHECK_TYPES for t in suite["tasks"])


def test_suite_rejects_bad_check_type(tmp_path, monkeypatch):
    bad = tmp_path / "suite.yaml"
    bad.write_text(
        "version: 9\ntasks:\n  - {id: x, category: c, prompt: p, check: {type: nope}}\n"
    )
    monkeypatch.setattr(bench, "SUITE_PATH", bad)
    with pytest.raises(bench.BenchError, match="unknown check type"):
        bench.load_suite()


@pytest.mark.parametrize(
    ("check", "answer", "expected"),
    [
        ({"type": "contains", "any": ["canberra"]}, "It's Canberra.", True),
        ({"type": "contains", "any": ["canberra"]}, "Sydney", False),
        ({"type": "regex", "pattern": r"^\W*BANANA\W*$"}, "BANANA.", True),
        ({"type": "regex", "pattern": r"^\W*BANANA\W*$"}, "I say BANANA", False),
        ({"type": "number", "value": 5, "tol": 0}, "The answer is 5", True),
        ({"type": "number", "value": 5, "tol": 0}, "5 cents? No, 10", False),
        ({"type": "number", "value": 1000, "tol": 0}, "1,000", True),
        ({"type": "number", "value": 5, "tol": 0}, "no digits here", False),
        ({"type": "json", "keys": ["name", "age"]}, '{"name": "a", "age": 1}', True),
        (
            {"type": "json", "keys": ["name", "age"]},
            'Sure:\n```json\n{"name": "a", "age": 1}\n```',
            True,
        ),
        ({"type": "json", "keys": ["name", "age"]}, '{"name": "a"}', False),
        ({"type": "json", "keys": ["name"]}, "[1, 2]", False),
    ],
)
def test_check_answer(check, answer, expected):
    assert bench.check_answer(check, answer) is expected


def test_check_answer_unknown_type_raises():
    with pytest.raises(bench.BenchError):
        bench.check_answer({"type": "magic"}, "x")


# --- Runner ----------------------------------------------------------------------


def _tiny_suite(tmp_path, monkeypatch):
    path = tmp_path / "suite.yaml"
    path.write_text(
        """
version: 3
tasks:
  - id: k1
    category: knowledge
    prompt: capital?
    check: {type: contains, any: [canberra]}
  - id: r1
    category: reasoning
    prompt: number?
    check: {type: number, value: 5, tol: 0}
  - id: t1
    category: tools
    prompt: time?
    check: {type: tool_called, tool: get_time, tools: [get_time]}
"""
    )
    monkeypatch.setattr(bench, "SUITE_PATH", path)


def test_run_suite_scores_writes_file_and_streams_events(tmp_path, monkeypatch):
    _tiny_suite(tmp_path, monkeypatch)
    answers = {"capital?": "Canberra", "number?": "It is 7"}

    def fake_chat_stats(messages, tools=None, model=None, options=None):
        assert model == "m-tools"
        return _reply(answers[messages[-1]["content"]], _stats(20, 2_000_000_000))

    def fake_run(
        prompt, conversation, model=None, *, tools=None, options=None, context=None
    ):
        assert tools == ["get_time"]
        conversation.add_user(prompt)
        conversation.add_assistant(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}],
            }
        )
        conversation.add_tool_result("get_time", "2026-01-01T00:00:00")
        conversation.add_assistant({"role": "assistant", "content": "It's midnight."})
        return "It's midnight."

    monkeypatch.setattr(ollama_client, "chat_stats", fake_chat_stats)
    monkeypatch.setattr(agent, "run", fake_run)

    job = jobstore.create("bench", {"model": "m-tools"})
    record = bench.run_suite("m-tools", job_id=job.id)

    assert record["model"] == "m-tools"
    assert record["tool_capable"] is True
    assert record["suite_version"] == 3
    assert record["overall"] == pytest.approx(2 / 3)
    assert record["categories"] == {"knowledge": 1.0, "reasoning": 0.0, "tools": 1.0}
    # 20 tokens / 2s twice -> 40 tokens over 4s = 10 tok/s (totals, not a mean)
    assert record["tokens_per_sec"] == pytest.approx(10.0)
    assert record["load_seconds"] == pytest.approx(0.5)
    assert [t["passed"] for t in record["tasks"]] == [True, False, True]
    assert record["tasks"][1]["expected"] == "= 5"

    stored = json.loads((tmp_path / "bench_results" / "m-tools.json").read_text())
    assert stored == record
    events = jobstore.load("bench", job.id).events
    assert [e["id"] for e in events] == ["k1", "r1", "t1"]
    assert all(e["type"] == "task" for e in events)


def test_run_suite_records_task_error_instead_of_failing(tmp_path, monkeypatch):
    _tiny_suite(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(ollama_client, "chat_stats", boom)
    monkeypatch.setattr(agent, "run", boom)

    record = bench.run_suite("m-plain")
    assert record["overall"] == 0
    assert record["tool_capable"] is False
    assert "model exploded" in record["tasks"][0]["error"]
    assert record["tokens_per_sec"] is None


def test_safe_result_filename_for_tags_with_slashes(tmp_path, monkeypatch):
    _tiny_suite(tmp_path, monkeypatch)
    monkeypatch.setattr(ollama_client, "chat_stats", lambda *a, **k: _reply("x"))
    monkeypatch.setattr(agent, "run", lambda *a, **k: "")
    bench.run_suite("hf.co/org/repo:Q4_K_M")
    assert (tmp_path / "bench_results" / "hf.co__org__repo__Q4_K_M.json").exists()
    assert bench.result("hf.co/org/repo:Q4_K_M")["model"] == "hf.co/org/repo:Q4_K_M"


def test_leaderboard_reads_rows_best_first(tmp_path):
    results = tmp_path / "bench_results"
    results.mkdir()
    for model, overall in (("a", 0.25), ("b", 0.75)):
        (results / f"{model}.json").write_text(
            json.dumps(
                {
                    "model": model,
                    "tool_capable": True,
                    "overall": overall,
                    "categories": {"coding": overall},
                    "tokens_per_sec": 1.0,
                    "load_seconds": 0.1,
                    "ran_at": "2026-01-01T00:00:00+00:00",
                    "suite_version": 1,
                    "tasks": [{"id": "x"}],
                }
            )
        )
    rows = bench.leaderboard()
    assert [r["model"] for r in rows] == ["b", "a"]
    assert set(rows[0]) == set(bench._ROW_KEYS)  # tasks stripped


def test_leaderboard_empty_when_no_results():
    assert bench.leaderboard() == []


def test_result_missing_raises():
    with pytest.raises(bench.BenchError, match="No benchmark result"):
        bench.result("nope")


def test_start_runs_in_background_and_succeeds(tmp_path, monkeypatch):
    _tiny_suite(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ollama_client, "chat_stats", lambda *a, **k: _reply("Canberra 5")
    )
    monkeypatch.setattr(agent, "run", lambda *a, **k: "")
    job = bench.start("m-tools")
    assert job.kind == "bench"
    assert job.payload == {"model": "m-tools", "options": {}}
    for _ in range(100):
        if jobstore.load("bench", job.id).status != "running":
            break
        time.sleep(0.05)
    done = jobstore.load("bench", job.id)
    assert done.status == "succeeded"
    assert done.result["model"] == "m-tools"
    assert len(done.events) == 3


def test_start_requires_model():
    with pytest.raises(bench.BenchError):
        bench.start("")


# --- Arena --------------------------------------------------------------------------


def test_parse_verdicts_maps_letters_back_to_models_tolerantly():
    raw = 'Here:\n```json\n{"a": {"score": 9.4, "rationale": "good"}, "B": 3}\n```'
    verdicts = bench.parse_verdicts(raw, ["m1", "m2", "m3"])
    assert verdicts[0] == {
        "type": "verdict",
        "model": "m1",
        "score": 9,
        "rationale": "good",
    }
    assert verdicts[1]["score"] == 3
    assert verdicts[2]["score"] is None
    assert "unparsed" in verdicts[2]


def test_parse_verdicts_garbage_never_raises():
    verdicts = bench.parse_verdicts("I refuse.", ["m1"])
    assert verdicts[0]["score"] is None
    assert verdicts[0]["unparsed"] == "I refuse."


def test_run_arena_answers_concurrently_and_judges(monkeypatch):
    calls = []

    def fake_chat_stats(messages, tools=None, model=None, options=None):
        calls.append(model)
        if model == "judge-model":
            assert options == {"temperature": 0}
            assert "ANSWER A" in messages[-1]["content"]
            assert "ANSWER B" in messages[-1]["content"]
            return _reply(
                '{"A": {"score": 8, "rationale": "r1"}, '
                '"B": {"score": 4, "rationale": "r2"}}'
            )
        if model == "bad":
            raise RuntimeError("down")
        return _reply(f"answer from {model}", _stats(30, 1_000_000_000))

    monkeypatch.setattr(ollama_client, "chat_stats", fake_chat_stats)
    job = jobstore.create("arena", {})
    result = bench.run_arena("why?", ["good", "bad"], "judge-model", job_id=job.id)

    assert result["prompt"] == "why?"
    assert result["judge"] == "judge-model"
    assert [a["model"] for a in result["answers"]] == ["good", "bad"]
    assert result["answers"][0]["content"] == "answer from good"
    assert result["answers"][0]["stats"]["tokens_per_sec"] == pytest.approx(30.0)
    assert "down" in result["answers"][1]["error"]
    assert [(v["model"], v["score"]) for v in result["verdicts"]] == [
        ("good", 8),
        ("bad", 4),
    ]
    events = jobstore.load("arena", job.id).events
    assert sorted(e["type"] for e in events) == [
        "answer",
        "answer",
        "verdict",
        "verdict",
    ]
    assert calls.count("judge-model") == 1


def test_run_arena_without_judge_has_no_verdicts(monkeypatch):
    monkeypatch.setattr(ollama_client, "chat_stats", lambda *a, **k: _reply("x"))
    result = bench.run_arena("p", ["a", "b"], None)
    assert result["verdicts"] == []
    assert len(result["answers"]) == 2


def test_start_arena_validates_and_resolves_auto_judge(monkeypatch):
    monkeypatch.setattr(bench.providers, "resolve", lambda role: f"resolved-{role}")
    monkeypatch.setattr(
        ollama_client, "chat_stats", lambda *a, **k: _reply('{"A": 5, "B": 5}')
    )
    with pytest.raises(bench.BenchError, match="prompt"):
        bench.start_arena("  ", ["a", "b"])
    with pytest.raises(bench.BenchError, match="two distinct"):
        bench.start_arena("p", ["a", "a"])
    job = bench.start_arena("p", ["a", "b"], judge="auto")
    assert job.payload["judge"] == "resolved-judge"
    assert job.payload["models"] == ["a", "b"]
    for _ in range(100):  # let the background thread finish inside the tmp dir
        if jobstore.load("arena", job.id).status != "running":
            break
        time.sleep(0.05)
    assert jobstore.load("arena", job.id).status == "succeeded"
