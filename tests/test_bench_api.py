"""Contract tests for api/bench.py against a mocked bench module."""

import pytest
from fastapi.testclient import TestClient

import bench
import jobstore
import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "RESULTS_DIR", tmp_path / "bench_results")
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    return TestClient(server.app)


_ROW = {
    "model": "m",
    "tool_capable": True,
    "overall": 0.5,
    "categories": {"coding": 0.5},
    "tokens_per_sec": 12.5,
    "load_seconds": 0.2,
    "ran_at": "2026-01-01T00:00:00+00:00",
    "suite_version": 1,
}


def test_suite_lists_tasks_with_check_type(client):
    body = client.get("/api/bench/suite").json()
    assert body["version"] == 1
    assert len(body["tasks"]) >= 20
    task = body["tasks"][0]
    assert set(task) == {"id", "category", "prompt", "check_type", "expected"}


def test_start_bench_returns_job(client, monkeypatch):
    captured = {}

    def fake_start(model, options=None):
        captured["args"] = (model, options)
        return jobstore.create("bench", {"model": model, "options": options or {}})

    monkeypatch.setattr(bench, "start", fake_start)
    response = client.post("/api/bench/runs", json={"model": "qwen2.5:latest"})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "bench"
    assert body["status"] == "running"
    assert body["payload"]["model"] == "qwen2.5:latest"
    assert captured["args"] == ("qwen2.5:latest", None)
    # and it's reachable through the generic jobs route
    assert client.get(f"/api/jobs/bench/{body['id']}").status_code == 200


def test_start_bench_rejects_empty_model(client):
    assert client.post("/api/bench/runs", json={"model": ""}).status_code == 400


def test_results_leaderboard_and_detail(client, monkeypatch):
    monkeypatch.setattr(bench, "leaderboard", lambda: [_ROW])
    monkeypatch.setattr(bench, "result", lambda model: {**_ROW, "tasks": [{"id": "x"}]})
    rows = client.get("/api/bench/results").json()
    assert rows == [_ROW]
    detail = client.get("/api/bench/results/hf.co/org/repo:Q4").json()
    assert detail["tasks"] == [{"id": "x"}]


def test_result_404_when_missing(client):
    response = client.get("/api/bench/results/nope")
    assert response.status_code == 404
    assert "No benchmark result" in response.json()["detail"]


def test_start_arena_returns_job_and_validates(client, monkeypatch):
    monkeypatch.setattr(
        bench,
        "start_arena",
        lambda prompt, models, judge=None, options=None: jobstore.create(
            "arena", {"prompt": prompt, "models": models, "judge": judge}
        ),
    )
    response = client.post(
        "/api/bench/arena",
        json={"prompt": "hi", "models": ["a", "b"], "judge": "auto"},
    )
    assert response.status_code == 200
    assert response.json()["payload"] == {
        "prompt": "hi",
        "models": ["a", "b"],
        "judge": "auto",
    }


def test_start_arena_400_on_bench_error(client):
    response = client.post("/api/bench/arena", json={"prompt": "hi", "models": ["a"]})
    assert response.status_code == 400
    assert "two distinct" in response.json()["detail"]
