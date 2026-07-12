"""HTTP API boundary around the existing assistant backend.

Wraps agent/memory/ingest/vectorstore UNCHANGED — they stay the source of
truth (CLAUDE.md: tool dispatch lives in agent.py, history lives in
memory.py). This module owns exactly one thing beyond routing: the single
server-side Conversation, mirroring what ui.py did with st.session_state —
one active conversation, no per-session state duplication.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import agent
import config
import ingest
import ollama_client
from memory import Conversation

app = FastAPI(title="Local AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_conversation: Conversation | None = None
_selected_model: str | None = None  # None = use config.get_model()'s default


def _get_conversation() -> Conversation:
    global _conversation
    if _conversation is None:
        _conversation = Conversation(system_prompt=agent.SYSTEM_PROMPT)
    return _conversation


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


@app.get("/api/conversation")
def get_conversation() -> list[dict]:
    return _get_conversation().messages


@app.post("/api/conversation/reset")
def reset_conversation() -> dict:
    global _conversation
    _conversation = Conversation(system_prompt=agent.SYSTEM_PROMPT)
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if _active_model() is None:
        raise HTTPException(
            status_code=503, detail="No model configured. Set OLLAMA_MODEL."
        )
    if not ollama_client.health_check():
        raise HTTPException(status_code=503, detail="Ollama is not reachable.")

    reply = agent.run(request.message, _get_conversation(), model=_selected_model)
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

    _get_conversation().add_system_note(
        f"The user uploaded a document named '{safe_name}'. Read its full "
        f"text with read_uploaded_document(filename='{safe_name}'), or answer "
        "specific questions about it with search_documents. Do not ask the "
        "user for a file path."
    )
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
