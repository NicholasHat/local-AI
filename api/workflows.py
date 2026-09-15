"""Workflow definition and run routes (Phase 23). Runs are jobstore jobs of
kind "workflow" — their record and live events are served by api/jobs.py
(/api/jobs/workflow/{id} and /events); this router only knows how to list,
edit, and start."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import projects
import workflows
from api.jobs import JobResponse, job_response

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowInputInfo(BaseModel):
    name: str
    type: str
    description: str
    required: bool
    default: object | None = None


class WorkflowStepInfo(BaseModel):
    id: str
    name: str
    prompt: str
    role: str
    model: str | None
    system: str
    tools: list[str]
    depends_on: list[str]
    each: str | None
    options: dict | None


class WorkflowInfo(BaseModel):
    name: str
    description: str
    inputs: list[WorkflowInputInfo]
    steps: list[WorkflowStepInfo]
    system: str
    output: str
    yaml: str
    builtin: bool = False


class WorkflowsResponse(BaseModel):
    workflows: list[WorkflowInfo]
    errors: list[str]


class WorkflowWriteRequest(BaseModel):
    yaml: str


class StartRunRequest(BaseModel):
    inputs: dict = {}
    project_id: str | None = None
    # The projects layer (Phase 24) passes the active project's attached
    # document filenames here so search_documents is scoped to them.
    doc_sources: list[str] | None = None


def _info(w: workflows.Workflow) -> WorkflowInfo:
    return WorkflowInfo(**w.to_dict())


@router.get("", response_model=WorkflowsResponse)
def list_workflows() -> WorkflowsResponse:
    valid, errors = workflows.discover()
    return WorkflowsResponse(workflows=[_info(w) for w in valid], errors=errors)


@router.get("/{name}", response_model=WorkflowInfo)
def get_workflow(name: str) -> WorkflowInfo:
    try:
        return _info(workflows.get(name))
    except workflows.WorkflowError as exc:
        status = 404 if "No such" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.put("/{name}", response_model=WorkflowInfo)
def save_workflow(name: str, request: WorkflowWriteRequest) -> WorkflowInfo:
    try:
        return _info(workflows.save(name, request.yaml))
    except workflows.WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{name}")
def delete_workflow(name: str) -> dict:
    try:
        workflows.delete(name)
    except workflows.WorkflowError as exc:
        status = 404 if "No such" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/{name}/runs", response_model=JobResponse)
def start_run(name: str, request: StartRunRequest) -> JobResponse:
    """Start a run. When a project is given, its attached documents scope
    search_documents for every step (unless doc_sources is passed
    explicitly) and the run is linked into the project."""
    doc_sources = request.doc_sources
    project = None
    if request.project_id:
        try:
            project = projects.get(request.project_id)
        except projects.ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if doc_sources is None:
            doc_sources = list(project["documents"])
    try:
        job = workflows.start(
            name,
            request.inputs,
            doc_sources=doc_sources,
            project_id=request.project_id,
        )
    except workflows.WorkflowError as exc:
        status = 404 if "No such" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if project is not None:
        projects.add_link(project["id"], "workflow", job.id, title=name)
    return job_response(job)
