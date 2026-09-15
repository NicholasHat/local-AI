"""Generic job routes (plan.md decision 1, Phases 19–26): fetch any job by
kind + id, list a kind, and stream a job's events over SSE. Every job kind
(bench, arena, workflow) is served here — the domain routers only add
the *start* endpoints that know how to build a payload."""

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import jobstore

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    payload: dict
    events: list[dict]
    result: dict | None
    error: str | None


class JobSummary(BaseModel):
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    payload: dict
    error: str | None


def job_response(job: jobstore.Job) -> JobResponse:
    return JobResponse(**job.to_dict())


def job_summary(job: jobstore.Job) -> JobSummary:
    return JobSummary(
        id=job.id,
        kind=job.kind,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        payload=job.payload,
        error=job.error,
    )


def load_or_404(kind: str, job_id: str) -> jobstore.Job:
    try:
        return jobstore.load(kind, job_id)
    except jobstore.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{kind}", response_model=list[JobSummary])
def list_jobs(kind: str, limit: int = 20) -> list[JobSummary]:
    try:
        return [job_summary(j) for j in jobstore.list_recent(kind, limit=limit)]
    except jobstore.JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kind}/{job_id}", response_model=JobResponse)
def get_job(kind: str, job_id: str) -> JobResponse:
    return job_response(load_or_404(kind, job_id))


@router.delete("/{kind}/{job_id}")
def delete_job(kind: str, job_id: str) -> dict:
    try:
        jobstore.delete(kind, job_id)
    except jobstore.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/{kind}/{job_id}/events")
def job_events(kind: str, job_id: str) -> StreamingResponse:
    """SSE stream of a job's events — polls the persisted record exactly
    like server.py's coding-run /events route, so it works no matter when a
    client connects relative to the background thread. Ends with one
    {"type": "status", ...} line once the job leaves `running`."""
    load_or_404(kind, job_id)

    def event_stream():
        sent = 0
        while True:
            try:
                job = jobstore.load(kind, job_id)
            except jobstore.JobError:
                return
            for event in job.events[sent:]:
                yield f"data: {json.dumps(event)}\n\n"
            sent = len(job.events)
            if job.status != "running":
                final = {"type": "status", "status": job.status, "error": job.error}
                yield f"data: {json.dumps(final)}\n\n"
                return
            time.sleep(0.3)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
