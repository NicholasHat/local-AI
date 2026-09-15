"""Contract tests for api/workflows.py via TestClient with a mocked
agent.run — no live model."""

import textwrap
import time

import pytest
from fastapi.testclient import TestClient

import agent
import jobstore
import projects
import server
import settings
import spaces
import workflows

DEMO = textwrap.dedent(
    """
    description: demo
    inputs:
      - {name: topic, type: string, description: what}
    steps:
      - id: first
        name: First
        prompt: "About {inputs.topic}"
      - id: second
        depends_on: [first]
        tools: [get_time]
        prompt: "Then {steps.first.output}"
    """
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(workflows, "WORKFLOWS_DIR", tmp_path / "workflows")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    return TestClient(server.app)


def _fake_run(
    user_message, conversation, model=None, *, tools=None, options=None, context=None
):
    return f"{context.agent_name}: {user_message}"


def test_list_get_put_delete(client):
    assert client.get("/api/workflows").json() == {"workflows": [], "errors": []}

    res = client.put("/api/workflows/demo", json={"yaml": DEMO})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "demo"
    assert body["output"] == "second"
    assert body["builtin"] is False
    assert body["yaml"] == DEMO
    assert body["inputs"] == [
        {
            "name": "topic",
            "type": "string",
            "description": "what",
            "required": True,
            "default": None,
        }
    ]
    assert [s["id"] for s in body["steps"]] == ["first", "second"]
    assert body["steps"][1]["tools"] == ["get_time"]
    assert body["steps"][1]["depends_on"] == ["first"]
    assert body["steps"][0]["name"] == "First"

    listed = client.get("/api/workflows").json()
    assert [w["name"] for w in listed["workflows"]] == ["demo"]
    assert client.get("/api/workflows/demo").json()["description"] == "demo"

    assert client.delete("/api/workflows/demo").json() == {"status": "ok"}
    assert client.get("/api/workflows/demo").status_code == 404
    assert client.delete("/api/workflows/demo").status_code == 404


def test_put_rejects_invalid_yaml_with_reason(client):
    res = client.put(
        "/api/workflows/demo",
        json={"yaml": "steps:\n  - id: a\n    tools: [write_file]\n    prompt: p"},
    )
    assert res.status_code == 400
    assert "unknown tool 'write_file'" in res.json()["detail"]
    assert client.get("/api/workflows").json()["workflows"] == []


def test_list_reports_malformed_files(client):
    workflows.WORKFLOWS_DIR.mkdir(parents=True)
    (workflows.WORKFLOWS_DIR / "bad.yaml").write_text("steps: []")
    body = client.get("/api/workflows").json()
    assert body["workflows"] == []
    assert len(body["errors"]) == 1 and "bad.yaml" in body["errors"][0]


def test_start_run_and_read_it_back_through_jobs(client, monkeypatch):
    monkeypatch.setattr(agent, "run", _fake_run)
    client.put("/api/workflows/demo", json={"yaml": DEMO})
    project_id = projects.create("Cats", "study cats")["id"]

    res = client.post(
        "/api/workflows/demo/runs",
        json={
            "inputs": {"topic": "cats"},
            "doc_sources": ["x.pdf"],
            "project_id": project_id,
        },
    )
    assert res.status_code == 200, res.text
    job = res.json()
    assert job["kind"] == "workflow"
    assert job["payload"]["name"] == "demo"
    assert job["payload"]["inputs"] == {"topic": "cats"}
    assert job["payload"]["project_id"] == project_id
    assert job["payload"]["doc_sources"] == ["x.pdf"]
    links = projects.get(project_id)["links"]
    assert [(link["kind"], link["id"]) for link in links] == [("workflow", job["id"])]
    space_id = job["payload"]["space_id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        job = client.get(f"/api/jobs/workflow/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded", job["error"]
    assert job["result"]["output"] == (
        "second @ test-model: Then first @ test-model: About cats"
    )
    assert job["result"]["space_id"] == space_id
    assert [e["type"] for e in job["events"]] == [
        "step_started",
        "step_finished",
        "step_started",
        "step_finished",
    ]
    posts = client.get(f"/api/spaces/{space_id}").json()["posts"]
    assert [p["author"] for p in posts] == ["first @ test-model", "second @ test-model"]

    summaries = client.get("/api/jobs/workflow").json()
    assert [s["id"] for s in summaries] == [job["id"]]


def test_start_run_errors(client):
    assert (
        client.post("/api/workflows/nope/runs", json={"inputs": {}}).status_code == 404
    )
    client.put("/api/workflows/demo", json={"yaml": DEMO})
    res = client.post("/api/workflows/demo/runs", json={"inputs": {}})
    assert res.status_code == 400
    assert "Missing required input 'topic'" in res.json()["detail"]


def test_start_run_scopes_documents_to_the_project(client, monkeypatch):
    seen = {}

    def fake_run(user_message, conversation, model=None, **kwargs):
        seen["doc_sources"] = kwargs["context"].doc_sources
        return "ok"

    monkeypatch.setattr(agent, "run", fake_run)
    client.put("/api/workflows/demo", json={"yaml": DEMO})
    project_id = projects.create("Cats", "study cats")["id"]
    projects.PROJECTS_DIR.mkdir(exist_ok=True)
    record = projects.get(project_id)
    record["documents"] = ["cats.pdf"]
    projects._write(record)

    res = client.post(
        "/api/workflows/demo/runs",
        json={"inputs": {"topic": "cats"}, "project_id": project_id},
    )
    assert res.status_code == 200, res.text
    assert res.json()["payload"]["doc_sources"] == ["cats.pdf"]
    deadline = time.time() + 10
    while time.time() < deadline and "doc_sources" not in seen:
        time.sleep(0.05)
    assert seen["doc_sources"] == ["cats.pdf"]
    assert (
        client.post(
            "/api/workflows/demo/runs", json={"inputs": {}, "project_id": "nope"}
        ).status_code
        == 404
    )
