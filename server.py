"""HTTP API boundary around the existing assistant backend, and — once
web/dist exists — the single process serving both the API and the built
React app (`uvicorn server:app`, browse to it directly).

Wraps agent/memory/ingest/vectorstore UNCHANGED — they stay the source of
truth (CLAUDE.md: tool dispatch lives in agent.py, history lives in
memory.py). This module owns routing plus one thing beyond it: which
conversation is currently active among the ones persisted by
conversations.py (Phase 14) — there's one active conversation at a time,
but many can exist in history.
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import config
import conversations
import ingest
import ollama_client
import skills
import vectorstore
from memory import Conversation

app = FastAPI(title="Local AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_active_conversation_id: str | None = None
_selected_model: str | None = None  # None = use config.get_model()'s default


def _active_id() -> str:
    """The active conversation's id, creating one on first use."""
    global _active_conversation_id
    if _active_conversation_id is None:
        _active_conversation_id, _ = conversations.create(
            system_prompt=agent.SYSTEM_PROMPT
        )
    return _active_conversation_id


def _get_conversation() -> Conversation:
    return conversations.load(_active_id())


def _active_model() -> str | None:
    if _selected_model:
        return _selected_model
    try:
        return config.get_model()
    except RuntimeError:
        return None


class HealthResponse(BaseModel):
    healthy: bool
    model: str | None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


class UploadResponse(BaseModel):
    filename: str
    chunks: int


class DocumentInfo(BaseModel):
    filename: str
    size_bytes: int


class ModelInfo(BaseModel):
    name: str
    size: int
    tool_capable: bool


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    current: str | None


class SetModelRequest(BaseModel):
    model: str


def _model_infos() -> list[ModelInfo]:
    return [
        ModelInfo(
            name=m["name"], size=m["size"], tool_capable="tools" in m["capabilities"]
        )
        for m in ollama_client.list_models()
    ]


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(healthy=ollama_client.health_check(), model=_active_model())


def _resolved_active_model(infos: list[ModelInfo]) -> str | None:
    """Resolve the active model to the exact tagged name the installed-models
    list uses, so a picker's selected value always matches a real option.

    Ollama accepts an untagged name (defaulting to :latest) for chat calls,
    but always reports installed models with an explicit tag — so
    config.get_model()'s raw value ("qwen2.5") won't match list_models()'
    tagged name ("qwen2.5:latest") unless resolved here.
    """
    model = _active_model()
    if model is None or any(m.name == model for m in infos):
        return model
    return next((m.name for m in infos if m.name.startswith(f"{model}:")), model)


@app.get("/api/models", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    infos = _model_infos()
    return ModelsResponse(models=infos, current=_resolved_active_model(infos))


@app.post("/api/settings/model", response_model=ModelsResponse)
def set_model(request: SetModelRequest) -> ModelsResponse:
    global _selected_model
    infos = _model_infos()
    match = next((m for m in infos if m.name == request.model), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {request.model!r}")
    if not match.tool_capable:
        raise HTTPException(
            status_code=400,
            detail=f"{request.model!r} doesn't support tool calling.",
        )
    _selected_model = request.model
    return ModelsResponse(models=infos, current=_selected_model)


# A small curated list of recommended tags — Ollama has no public model
# search API, so this is hand-maintained, not a live catalog. Any tag can
# still be pulled directly via POST /api/models/pull regardless of this list.
_MODEL_LIBRARY = [
    {
        "name": "qwen2.5",
        "description": "Strong tool-calling, good general default.",
        "tool_capable": True,
    },
    {
        "name": "llama3.1",
        "description": "Meta's Llama 3.1 — tool-calling capable, widely used.",
        "tool_capable": True,
    },
    {
        "name": "mistral",
        "description": "Fast 7B model, tool-calling capable.",
        "tool_capable": True,
    },
    {
        "name": "gemma2",
        "description": "Google's Gemma 2 — strong general-purpose, no tool-calling.",
        "tool_capable": False,
    },
    {
        "name": "phi3",
        "description": "Small and fast, no tool-calling.",
        "tool_capable": False,
    },
    {
        "name": "nomic-embed-text",
        "description": "Embedding model used for this app's document search.",
        "tool_capable": False,
    },
]


class ModelLibraryEntry(BaseModel):
    name: str
    description: str
    tool_capable: bool


class PullModelRequest(BaseModel):
    name: str


@app.get("/api/models/library", response_model=list[ModelLibraryEntry])
def model_library() -> list[ModelLibraryEntry]:
    return [ModelLibraryEntry(**m) for m in _MODEL_LIBRARY]


@app.post("/api/models/pull")
def pull_model(request: PullModelRequest) -> StreamingResponse:
    """SSE stream of pull progress — this app's first streaming route (the
    same primitive earmarked for token-streamed chat replies later)."""

    def event_stream():
        for update in ollama_client.pull_model(request.name):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/api/models/{name}")
def delete_model_endpoint(name: str) -> dict:
    try:
        ollama_client.delete_model(name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@app.get("/api/conversation")
def get_conversation() -> list[dict]:
    return _get_conversation().messages


class ConversationMetaResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


def _meta_response(meta: conversations.ConversationMeta) -> ConversationMetaResponse:
    return ConversationMetaResponse(
        id=meta.id,
        title=meta.title,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
    )


@app.get("/api/conversations", response_model=list[ConversationMetaResponse])
def list_conversations() -> list[ConversationMetaResponse]:
    """The short history list, newest first — including the active one."""
    return [_meta_response(m) for m in conversations.list_recent()]


@app.get("/api/conversations/active", response_model=ConversationMetaResponse)
def get_active_conversation() -> ConversationMetaResponse:
    """Which conversation the sidebar's history list should highlight."""
    return _meta_response(conversations.get_meta(_active_id()))


@app.post("/api/conversations", response_model=ConversationMetaResponse)
def new_conversation() -> ConversationMetaResponse:
    """Start a new chat. Unlike the old reset endpoint, the previous
    conversation is kept in history, not overwritten."""
    global _active_conversation_id
    _active_conversation_id, _ = conversations.create(system_prompt=agent.SYSTEM_PROMPT)
    return _meta_response(conversations.get_meta(_active_conversation_id))


@app.post(
    "/api/conversations/{conversation_id}/activate",
    response_model=ConversationMetaResponse,
)
def activate_conversation(conversation_id: str) -> ConversationMetaResponse:
    global _active_conversation_id
    meta = conversations.get_meta(conversation_id)
    if meta is None:
        raise HTTPException(
            status_code=404, detail=f"No such conversation: {conversation_id!r}"
        )
    _active_conversation_id = conversation_id
    return _meta_response(meta)


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    global _active_conversation_id
    try:
        conversations.delete(conversation_id)
    except conversations.ConversationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if _active_conversation_id == conversation_id:
        remaining = conversations.list_recent(limit=1)
        _active_conversation_id = remaining[0].id if remaining else None
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if _active_model() is None:
        raise HTTPException(
            status_code=503, detail="No model configured. Set OLLAMA_MODEL."
        )
    if not ollama_client.health_check():
        raise HTTPException(status_code=503, detail="Ollama is not reachable.")

    conversation_id = _active_id()
    conversation = conversations.load(conversation_id)
    reply = agent.run(request.message, conversation, model=_selected_model)
    conversations.save(conversation_id, conversation)
    return ChatResponse(reply=reply)


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile) -> UploadResponse:
    upload_dir = config.get_upload_dir()
    upload_dir.mkdir(exist_ok=True)
    safe_name = Path(file.filename).name
    dest = upload_dir / safe_name
    dest.write_bytes(await file.read())

    try:
        chunks = ingest.ingest_pdf(str(dest))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to index: {exc}") from exc

    conversation_id = _active_id()
    conversation = conversations.load(conversation_id)
    conversation.add_system_note(
        f"The user uploaded a document named '{safe_name}'. Read its full "
        f"text with read_uploaded_document(filename='{safe_name}'), or answer "
        "specific questions about it with search_documents. Do not ask the "
        "user for a file path."
    )
    conversations.save(conversation_id, conversation)
    return UploadResponse(filename=safe_name, chunks=chunks)


@app.get("/api/documents", response_model=list[DocumentInfo])
def list_documents() -> list[DocumentInfo]:
    upload_dir = config.get_upload_dir()
    if not upload_dir.exists():
        return []
    return sorted(
        (
            DocumentInfo(filename=p.name, size_bytes=p.stat().st_size)
            for p in upload_dir.iterdir()
            if p.is_file()
        ),
        key=lambda d: d.filename,
    )


@app.delete("/api/documents/{filename}")
def delete_document(filename: str) -> dict:
    """Path-traversal-safe via resolved-path containment, not a `.name`
    comparison — `Path("..").name` is `".."` (unchanged), so a bare ".."
    would slip past a naive equality check; resolving and checking the
    parent directory catches it regardless of the filename's shape."""
    upload_dir = config.get_upload_dir()
    path = (upload_dir / filename).resolve()
    if path.parent != upload_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No such document: {filename!r}")

    path.unlink()
    vectorstore.delete_by_source(path.name)
    return {"status": "ok"}


class SkillInfo(BaseModel):
    name: str
    description: str
    kind: str
    parameters: dict
    required: list[str]
    body: str


class SkillWriteRequest(BaseModel):
    name: str
    description: str
    parameters: dict = {}
    required: list[str] = []
    prompt: str | None = None
    code: str | None = None


def _skill_info(s: skills.Skill) -> SkillInfo:
    return SkillInfo(
        name=s.name,
        description=s.description,
        kind=s.kind,
        parameters=s.parameters,
        required=s.required,
        body=s.body,
    )


def _write_and_fetch(request: SkillWriteRequest) -> SkillInfo:
    try:
        skills.write_skill(
            request.name,
            request.description,
            request.parameters,
            request.required,
            prompt=request.prompt,
            code=request.code,
        )
    except skills.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    valid, _errors = skills.discover()
    created = next(s for s in valid if s.name == request.name)
    return _skill_info(created)


@app.get("/api/skills", response_model=list[SkillInfo])
def list_skills() -> list[SkillInfo]:
    valid, _errors = skills.discover()
    return [_skill_info(s) for s in valid]


@app.post("/api/skills", response_model=SkillInfo)
def create_skill_endpoint(request: SkillWriteRequest) -> SkillInfo:
    return _write_and_fetch(request)


@app.put("/api/skills/{name}", response_model=SkillInfo)
def update_skill_endpoint(name: str, request: SkillWriteRequest) -> SkillInfo:
    if request.name != name:
        raise HTTPException(
            status_code=400, detail="Path name and body name must match."
        )
    return _write_and_fetch(request)


@app.delete("/api/skills/{name}")
def delete_skill_endpoint(name: str) -> dict:
    try:
        skills.delete_skill(name)
    except skills.SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


# Serve the built React app, if present. Must be mounted LAST — Starlette
# matches routes in registration order, and a "/" mount would otherwise
# shadow every /api/* route above it. Absent until `cd web && npm run
# build`; the API still works standalone against the Vite dev server in the
# meantime (see vite.config.ts's dev proxy).
_WEB_DIST = Path(__file__).parent / "web" / "dist"
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")
