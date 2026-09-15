"""jobstore.py — the generic background-job record (Phase 19)."""

import threading

import pytest

import jobstore


@pytest.fixture(autouse=True)
def isolated_jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")


def test_create_load_roundtrip():
    job = jobstore.create("bench", {"model": "m"})
    loaded = jobstore.load("bench", job.id)
    assert loaded.status == "running"
    assert loaded.payload == {"model": "m"}
    assert loaded.events == []
    assert loaded.result is None


def test_events_get_timestamps_and_order():
    job = jobstore.create("arena", {})
    jobstore.append_event("arena", job.id, {"type": "a"})
    jobstore.append_event("arena", job.id, {"type": "b", "ts": "fixed"})
    events = jobstore.load("arena", job.id).events
    assert [e["type"] for e in events] == ["a", "b"]
    assert events[0]["ts"] and events[1]["ts"] == "fixed"


def test_succeed_and_fail_are_terminal():
    ok = jobstore.create("workflow", {})
    jobstore.succeed("workflow", ok.id, {"output": "x"})
    assert jobstore.load("workflow", ok.id).status == "succeeded"
    assert jobstore.load("workflow", ok.id).result == {"output": "x"}

    bad = jobstore.create("workflow", {})
    jobstore.fail("workflow", bad.id, "boom")
    failed = jobstore.load("workflow", bad.id)
    assert failed.status == "failed" and failed.error == "boom"


def test_invalid_kind_and_status_rejected():
    with pytest.raises(jobstore.JobError):
        jobstore.create("../evil", {})
    job = jobstore.create("bench", {})
    with pytest.raises(jobstore.JobError):
        jobstore.set_status("bench", job.id, "weird")


def test_list_recent_is_per_kind_newest_first():
    a = jobstore.create("bench", {"n": 1})
    b = jobstore.create("bench", {"n": 2})
    jobstore.create("arena", {})
    jobstore.append_event("bench", a.id, {"type": "touch"})  # a becomes newest
    ids = [j.id for j in jobstore.list_recent("bench")]
    assert ids == [a.id, b.id]


def test_delete_and_missing():
    job = jobstore.create("bench", {})
    jobstore.delete("bench", job.id)
    with pytest.raises(jobstore.JobError):
        jobstore.load("bench", job.id)
    with pytest.raises(jobstore.JobError):
        jobstore.delete("bench", "nope")


def test_run_in_background_records_result_and_errors():
    done = threading.Event()

    def work(job_id):
        jobstore.append_event("bench", job_id, {"type": "step"})
        done.set()
        return {"score": 1}

    job = jobstore.run_in_background("bench", {"m": 1}, work)
    assert done.wait(5)
    # the terminal write happens right after fn returns; poll briefly
    for _ in range(50):
        loaded = jobstore.load("bench", job.id)
        if loaded.status != "running":
            break
        threading.Event().wait(0.02)
    assert loaded.status == "succeeded" and loaded.result == {"score": 1}

    def explode(job_id):
        raise RuntimeError("kaboom")

    job = jobstore.run_in_background("bench", {}, explode)
    for _ in range(50):
        loaded = jobstore.load("bench", job.id)
        if loaded.status != "running":
            break
        threading.Event().wait(0.02)
    assert loaded.status == "failed" and "kaboom" in loaded.error


def test_run_in_background_survives_record_deleted_mid_run(capsys):
    gate = threading.Event()
    deleted = threading.Event()

    def work(job_id):
        gate.wait(5)
        raise RuntimeError("late failure")

    job = jobstore.run_in_background("bench", {}, work)
    jobstore.delete("bench", job.id)
    deleted.set()
    gate.set()
    for t in threading.enumerate():
        if t.name == f"bench-{job.id}":
            t.join(5)
    # The worker's failure had nowhere to land; it must not spray a traceback
    # (threading prints unhandled exceptions to stderr).
    assert "Traceback" not in capsys.readouterr().err
