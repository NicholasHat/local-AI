"""Contract tests for the Phase 19–21 routers: jobs, spaces, providers."""

import pytest
from fastapi.testclient import TestClient

import jobstore
import ollama_client
import providers
import server
import settings
import spaces


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(providers, "PROVIDERS_DIR", tmp_path / "providers")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")
    return TestClient(server.app)


# --- jobs -------------------------------------------------------------------


def test_jobs_get_list_delete_and_events(client):
    job = jobstore.create("bench", {"model": "m"})
    jobstore.append_event("bench", job.id, {"type": "task", "id": "t1"})
    jobstore.succeed("bench", job.id, {"overall": 1.0})

    detail = client.get(f"/api/jobs/bench/{job.id}").json()
    assert detail["status"] == "succeeded" and detail["result"] == {"overall": 1.0}
    assert detail["events"][0]["id"] == "t1"

    listing = client.get("/api/jobs/bench").json()
    assert [j["id"] for j in listing] == [job.id]
    assert "events" not in listing[0]

    with client.stream("GET", f"/api/jobs/bench/{job.id}/events") as response:
        body = "".join(response.iter_text())
    assert '"id": "t1"' in body and '"status": "succeeded"' in body

    assert client.get("/api/jobs/bench/nope").status_code == 404
    assert client.get("/api/jobs/bench/nope/events").status_code == 404
    assert client.delete(f"/api/jobs/bench/{job.id}").json() == {"status": "ok"}
    assert client.get("/api/jobs/bench").json() == []
    assert client.get("/api/jobs/Bad%20Kind").status_code == 400


# --- spaces -----------------------------------------------------------------


def test_spaces_crud_and_posting(client):
    created = client.post("/api/spaces", json={"name": "board", "purpose": "p"})
    assert created.status_code == 200
    space_id = created.json()["id"]

    post = client.post(f"/api/spaces/{space_id}/posts", json={"content": "hi"})
    assert post.json()["author"] == "user"
    detail = client.get(f"/api/spaces/{space_id}").json()
    assert [p["content"] for p in detail["posts"]] == ["hi"]
    assert client.get("/api/spaces").json()[0]["post_count"] == 1

    assert client.post("/api/spaces", json={"name": " "}).status_code == 400
    assert (
        client.post("/api/spaces/nope/posts", json={"content": "x"}).status_code == 404
    )
    assert (
        client.post(f"/api/spaces/{space_id}/posts", json={"content": ""}).status_code
        == 400
    )
    assert client.delete(f"/api/spaces/{space_id}").json() == {"status": "ok"}
    assert client.get(f"/api/spaces/{space_id}").status_code == 404


# --- providers --------------------------------------------------------------


def test_providers_list_create_activate_delete(client):
    initial = client.get("/api/providers").json()
    assert initial["active"] == "default"
    assert initial["resolved"]["chat"] == "env-model"
    assert initial["roles"] == list(providers.ROLES)

    body = {"name": "mine", "description": "d", "routes": {"chat": "qwen2.5:latest"}}
    created = client.post("/api/providers", json=body).json()
    assert [p["name"] for p in created["providers"]] == ["default", "mine"]

    activated = client.post("/api/providers/mine/activate").json()
    assert activated["active"] == "mine"
    assert activated["resolved"]["chat"] == "qwen2.5:latest"
    assert activated["resolved"]["coding"] == "env-model"
    assert client.get("/api/health").json()["model"] == "qwen2.5:latest"

    assert (
        client.post("/api/providers", json={**body, "routes": {"x": "y"}}).status_code
        == 400
    )
    assert client.put("/api/providers/other", json=body).status_code == 400
    assert client.delete("/api/providers/default").status_code == 400
    assert client.post("/api/providers/nope/activate").status_code == 404

    deleted = client.delete("/api/providers/mine").json()
    assert deleted["active"] == "default"


def test_providers_recommend_preview_and_save(client, monkeypatch):
    import bench

    monkeypatch.setattr(
        ollama_client,
        "list_models",
        lambda: [{"name": "m1", "size": 1, "digest": None, "capabilities": ["tools"]}],
    )
    monkeypatch.setattr(
        bench,
        "leaderboard",
        lambda: [
            {
                "model": "m1",
                "tool_capable": True,
                "overall": 0.8,
                "categories": {"reasoning": 0.8, "coding": 0.7},
                "tokens_per_sec": 30.0,
            },
            {
                "model": "not-installed",
                "tool_capable": True,
                "overall": 0.99,
                "categories": {"reasoning": 1.0, "coding": 1.0},
                "tokens_per_sec": 30.0,
            },
        ],
    )
    preview = client.post("/api/providers/recommend", json={}).json()
    assert preview["routes"]["chat"] == "m1" and preview["routes"]["coding"] == "m1"
    assert [p["name"] for p in client.get("/api/providers").json()["providers"]] == [
        "default"
    ]

    saved = client.post("/api/providers/recommend", json={"save": True, "name": "best"})
    assert saved.status_code == 200
    assert "best" in [
        p["name"] for p in client.get("/api/providers").json()["providers"]
    ]


def test_providers_recommend_without_results(client, monkeypatch):
    import bench

    monkeypatch.setattr(ollama_client, "list_models", lambda: [])
    monkeypatch.setattr(bench, "leaderboard", lambda: [])
    assert client.post("/api/providers/recommend", json={}).status_code == 400
