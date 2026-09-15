"""Live E2E for Phases 19–25: spaces as a channel between two agent
identities, a council workflow across two installed models, an arena
comparison, the live update check, and a vault export. Loose assertions
only (a tool was called, a post exists, an output is non-empty) — never
exact model prose."""

import time

import pytest

import agent
import bench
import catalog
import jobstore
import ollama_client
import settings
import spaces
import vault
import workflows
from memory import Conversation

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")


def _chat_models(minimum: int) -> list[str]:
    names = [
        m["name"]
        for m in ollama_client.list_models()
        if "embedding" not in m["capabilities"]
    ]
    if len(names) < minimum:
        pytest.skip(f"needs {minimum} installed chat models, have {len(names)}")
    return names


def _wait(kind: str, job_id: str, timeout: float) -> jobstore.Job:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobstore.load(kind, job_id)
        if job.status != "running":
            return job
        time.sleep(1)
    raise AssertionError(f"{kind} job {job_id} still running after {timeout}s")


def test_two_agents_converse_through_a_space():
    space = spaces.create("e2e", purpose="handoff")
    writer = Conversation(system_prompt=agent.SYSTEM_PROMPT)
    agent.run(
        f"Use post_to_space to post exactly this text to space {space['id']}: "
        "'The launch date is 14 March.' Then reply 'posted'.",
        writer,
        tools=["post_to_space"],
        context=agent.RunContext(agent_name="writer"),
    )
    posts = spaces.get(space["id"])["posts"]
    assert posts and posts[0]["author"] == "writer"
    assert "14 March" in posts[0]["content"]

    reader = Conversation(system_prompt=agent.SYSTEM_PROMPT)
    reply = agent.run(
        f"Read space {space['id']} with read_space and tell me the launch date.",
        reader,
        tools=["read_space"],
        context=agent.RunContext(agent_name="reader"),
    )
    assert any(m["role"] == "tool" for m in reader.messages)
    assert "march" in reply.lower() or "14" in reply


def test_council_workflow_across_two_models():
    models = _chat_models(2)[:2]
    job = workflows.start(
        "council",
        {
            "question": "Is Python or Rust better for a small CLI tool?",
            "models": models,
        },
    )
    done = _wait("workflow", job.id, timeout=900)
    assert done.status == "succeeded", done.error
    assert done.result["output"].strip()
    posts = spaces.get(done.payload["space_id"])["posts"]
    authors = {p["author"] for p in posts}
    assert len(authors) >= 3  # two voices + the synthesis
    assert all(any(m in a for a in authors) for m in models)


def test_arena_compares_two_models_with_stats():
    models = _chat_models(2)[:2]
    result = bench.run_arena("In one sentence, what is a hash map?", models, judge=None)
    assert [a["model"] for a in result["answers"]] == models
    for answer in result["answers"]:
        assert answer.get("error") is None
        assert answer["content"].strip()
        assert answer["stats"]["seconds"] > 0


def test_update_check_reports_a_status_per_installed_model():
    installed = ollama_client.list_models()
    report = catalog.check_updates(installed, refresh=True)
    if report.get("offline"):
        pytest.skip(f"registry unreachable: {report.get('error')}")
    statuses = {m["name"]: m["status"] for m in report["models"]}
    assert set(statuses) == {m["name"] for m in installed}
    assert set(statuses.values()) <= {
        "up_to_date",
        "update_available",
        "unknown",
        "skipped",
    }


def test_vault_export_copies_every_blob(tmp_path):
    smallest = min(ollama_client.list_models(), key=lambda m: m["size"])
    meta = vault.export_model(smallest["name"], vault_dir=tmp_path / "vault")
    entry = next(
        e for e in vault.list_vault(tmp_path / "vault") if e["name"] == smallest["name"]
    )
    assert entry["blobs"] == meta["blobs"] >= 1
    blob_files = list((tmp_path / "vault").glob("*/blobs/sha256-*"))
    assert len(blob_files) == meta["blobs"]
