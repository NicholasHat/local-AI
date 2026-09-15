"""Project routes (Phase 24) plus the two hooks server.py's chat route
calls: chat_context() (the active project's document filter + goal/notes
as ephemeral system context) and link_conversation()."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import projects
from agent import RunContext

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectSummary(BaseModel):
    id: str
    name: str
    goal: str
    created_at: str
    updated_at: str
    document_count: int


class ProjectLink(BaseModel):
    kind: str
    id: str
    title: str
    ts: str


class ProjectDetail(BaseModel):
    id: str
    name: str
    goal: str
    notes: str
    documents: list[str]
    conversation_ids: list[str]
    links: list[ProjectLink]
    space_id: str
    created_at: str
    updated_at: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectSummary]
    active: str | None


class CreateProjectRequest(BaseModel):
    name: str
    goal: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    goal: str | None = None
    notes: str | None = None


class AttachDocumentRequest(BaseModel):
    filename: str


class AppendNotesRequest(BaseModel):
    text: str
    heading: str | None = None


class AddLinkRequest(BaseModel):
    kind: str
    id: str
    title: str = ""


def _status(exc: projects.ProjectError) -> int:
    return 404 if "No such" in str(exc) else 400


def _detail(raw: dict) -> ProjectDetail:
    return ProjectDetail(**raw)


def _run(fn, *args) -> ProjectDetail:
    try:
        return _detail(fn(*args))
    except projects.ProjectError as exc:
        raise HTTPException(status_code=_status(exc), detail=str(exc)) from exc


# --- Hooks used by server.py's chat route ------------------------------------


def chat_context() -> RunContext:
    """The RunContext for a chat turn. With a project active: search is
    scoped to its attached documents and the model sees its goal + notes
    (ephemeral system context — never written into history)."""
    project = projects.active()
    if project is None:
        return RunContext()
    lines = [f"Active project '{project['name']}'."]
    if project["goal"]:
        lines.append(f"Goal: {project['goal']}")
    if project["documents"]:
        lines.append("Attached documents: " + ", ".join(project["documents"]))
    if project["notes"].strip():
        lines.append(f"Notes:\n{project['notes'].strip()}")
    return RunContext(
        doc_sources=list(project["documents"]), system_context="\n".join(lines)
    )


def link_conversation(conversation_id: str) -> None:
    """Record the conversation on the active project (no-op when none)."""
    project = projects.active()
    if project is not None:
        projects.add_conversation(project["id"], conversation_id)


# --- Routes ------------------------------------------------------------------


def _list() -> ProjectsResponse:
    active = projects.active()
    return ProjectsResponse(
        projects=[ProjectSummary(**m.__dict__) for m in projects.list_recent()],
        active=active["id"] if active else None,
    )


@router.get("", response_model=ProjectsResponse)
def list_projects() -> ProjectsResponse:
    return _list()


@router.post("", response_model=ProjectDetail)
def create_project(request: CreateProjectRequest) -> ProjectDetail:
    return _run(projects.create, request.name, request.goal)


@router.post("/deactivate", response_model=ProjectsResponse)
def deactivate_project() -> ProjectsResponse:
    projects.deactivate()
    return _list()


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str) -> ProjectDetail:
    return _run(projects.get, project_id)


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, request: UpdateProjectRequest) -> ProjectDetail:
    return _run(projects.update, project_id, request.name, request.goal, request.notes)


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict:
    try:
        projects.delete(project_id)
    except projects.ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/{project_id}/activate", response_model=ProjectsResponse)
def activate_project(project_id: str) -> ProjectsResponse:
    try:
        projects.activate(project_id)
    except projects.ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _list()


@router.post("/{project_id}/documents", response_model=ProjectDetail)
def attach_document(project_id: str, request: AttachDocumentRequest) -> ProjectDetail:
    return _run(projects.attach_document, project_id, request.filename)


@router.delete("/{project_id}/documents/{filename}", response_model=ProjectDetail)
def detach_document(project_id: str, filename: str) -> ProjectDetail:
    return _run(projects.detach_document, project_id, filename)


@router.post("/{project_id}/notes/append", response_model=ProjectDetail)
def append_notes(project_id: str, request: AppendNotesRequest) -> ProjectDetail:
    return _run(projects.append_notes, project_id, request.text, request.heading)


@router.post("/{project_id}/links", response_model=ProjectDetail)
def add_link(project_id: str, request: AddLinkRequest) -> ProjectDetail:
    return _run(projects.add_link, project_id, request.kind, request.id, request.title)
