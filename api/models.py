"""Model explorer, catalog, updates, vault, and custom-model routes
(Phase 25). The router's prefix is /api/models; server.py still owns
GET /api/models, POST /api/models/pull and DELETE /api/models/{name}, so
nothing here defines an empty path. Model names carry ':' and '/', so path
params use `{name:path}`."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import catalog
import config
import ollama_client
import settings
import vault

router = APIRouter(prefix="/api/models", tags=["models"])


# --- Library (the shape ModelManager.tsx already consumes) -------------------


class ModelLibraryEntry(BaseModel):
    name: str
    description: str
    tool_capable: bool


@router.get("/library", response_model=list[ModelLibraryEntry])
def model_library() -> list[ModelLibraryEntry]:
    return [ModelLibraryEntry(**m) for m in catalog.library()]


# --- Installed models, in full -----------------------------------------------


class InstalledModel(BaseModel):
    name: str
    size: int
    digest: str | None
    capabilities: list[str]
    tool_capable: bool
    running: bool
    family: str
    families: list[str]
    parameter_size: str
    quantization_level: str
    format: str
    architecture: str
    context_length: int | None
    parameter_count: int | None
    license: str
    license_link: str
    base_model: str
    modified_at: str | None
    template: str
    system: str
    parameters: str


def _installed(model: dict, running: set[str]) -> InstalledModel:
    details = ollama_client.show_model(model["name"])
    return InstalledModel(
        size=model["size"],
        digest=model.get("digest"),
        tool_capable="tools" in model["capabilities"],
        running=model["name"] in running,
        **details,
    )


def _running_names() -> set[str]:
    return {m["name"] for m in ollama_client.running_models()}


@router.get("/installed", response_model=list[InstalledModel])
def installed_models() -> list[InstalledModel]:
    running = _running_names()
    return [_installed(m, running) for m in ollama_client.list_models()]


@router.get("/installed/{name:path}", response_model=InstalledModel)
def installed_model(name: str) -> InstalledModel:
    match = next((m for m in ollama_client.list_models() if m["name"] == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Not installed: {name!r}")
    return _installed(match, _running_names())


class RunningModel(BaseModel):
    name: str
    size: int | None
    size_vram: int | None
    expires_at: str | None


@router.get("/running", response_model=list[RunningModel])
def running_models() -> list[RunningModel]:
    return [RunningModel(**m) for m in ollama_client.running_models()]


# --- Catalog + live feeds -------------------------------------------------------


class CatalogTag(BaseModel):
    tag: str
    size: str
    installed: bool


class CatalogModel(BaseModel):
    name: str
    org: str
    family: str
    category: str
    description: str
    license: str
    capabilities: list[str]
    recommended: bool
    ollama_tags: list[CatalogTag]
    hf_repo: str
    notes: str
    installed_tags: list[str]
    installed_any: bool


class CatalogResponse(BaseModel):
    updated: str
    note: str
    models: list[CatalogModel]
    errors: list[str]


@router.get("/catalog", response_model=CatalogResponse)
def model_catalog() -> CatalogResponse:
    try:
        return CatalogResponse(**catalog.catalog(ollama_client.list_models()))
    except catalog.CatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class TrendingEntry(BaseModel):
    repo: str
    pull_tag: str
    likes: int
    downloads: int
    trending_score: float
    pipeline: str
    license: str
    created_at: str


class TrendingResponse(BaseModel):
    entries: list[TrendingEntry] = []
    fetched_at: str | None = None
    error: str | None = None
    offline: bool = False


@router.get("/trending", response_model=TrendingResponse)
def trending(limit: int = 20, refresh: bool = False) -> TrendingResponse:
    return TrendingResponse(**catalog.trending(limit=limit, refresh=refresh))


class UpdateStatus(BaseModel):
    name: str
    status: str  # up_to_date | update_available | unknown | skipped
    reason: str | None = None
    local_digest: str | None = None
    remote_digest: str | None = None


class UpdatesResponse(BaseModel):
    models: list[UpdateStatus] = []
    checked_at: str | None = None
    error: str | None = None
    offline: bool = False


@router.get("/updates", response_model=UpdatesResponse)
def updates(refresh: bool = False) -> UpdatesResponse:
    return UpdatesResponse(
        **catalog.check_updates(ollama_client.list_models(), refresh=refresh)
    )


# --- Custom builds ----------------------------------------------------------------


class CreateModelRequest(BaseModel):
    name: str
    from_model: str
    system: str | None = None
    parameters: dict | None = None
    template: str | None = None


class CreateModelResponse(BaseModel):
    name: str
    status: str


@router.post("/create", response_model=CreateModelResponse)
def create_model(request: CreateModelRequest) -> CreateModelResponse:
    """`ollama create`: a new local tag from an installed base plus a system
    prompt / parameters / template. The result vaults like any other model."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="A model name is required.")
    try:
        result = ollama_client.create_model(
            request.name,
            request.from_model,
            system=request.system,
            parameters=request.parameters,
            template=request.template,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateModelResponse(
        name=request.name, status=str(result.get("status", "ok"))
    )


# --- Vault -----------------------------------------------------------------------


class VaultEntry(BaseModel):
    name: str
    safe_name: str
    exported_at: str | None = None
    size: int | None = None
    blobs: int | None = None
    details: dict = {}
    error: str | None = None
    installed: bool = False


class VaultResponse(BaseModel):
    vault_dir: str
    entries: list[VaultEntry]


class VaultModelRequest(BaseModel):
    name: str


class VaultTransferResponse(BaseModel):
    name: str
    size: int | None = None
    blobs: int | None = None
    copied_blobs: int


def _vault_response() -> VaultResponse:
    installed = {m["name"] for m in ollama_client.list_models()}
    entries = [
        VaultEntry(**m, installed=m.get("name") in installed)
        for m in vault.list_vault()
    ]
    return VaultResponse(vault_dir=str(config.get_vault_dir()), entries=entries)


@router.get("/vault", response_model=VaultResponse)
def list_vault() -> VaultResponse:
    return _vault_response()


@router.post("/vault/export", response_model=VaultTransferResponse)
def vault_export(request: VaultModelRequest) -> VaultTransferResponse:
    try:
        details = ollama_client.show_model(request.name)
    except Exception:  # not installed / server error — vault.py reports the manifest
        details = {}
    try:
        meta = vault.export_model(request.name, details=details)
    except vault.VaultError as exc:
        status = 404 if "not installed" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return VaultTransferResponse(
        name=meta["name"],
        size=meta["size"],
        blobs=meta["blobs"],
        copied_blobs=meta["copied_blobs"],
    )


@router.post("/vault/import", response_model=VaultTransferResponse)
def vault_import(request: VaultModelRequest) -> VaultTransferResponse:
    try:
        meta = vault.import_model(request.name)
    except vault.VaultError as exc:
        status = 404 if "not in the vault" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return VaultTransferResponse(
        name=meta["name"],
        size=meta.get("size"),
        blobs=meta.get("blobs"),
        copied_blobs=meta["copied_blobs"],
    )


@router.delete("/vault/{name:path}", response_model=VaultResponse)
def vault_delete(name: str) -> VaultResponse:
    try:
        vault.delete_from_vault(name)
    except vault.VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _vault_response()


# Registered LAST in this router: `{name:path}` would otherwise swallow
# /vault/<name> and every other sub-path above it.
@router.delete("/{name:path}")
def delete_model(name: str) -> dict:
    """`{name:path}` because pulled Hugging Face tags contain slashes
    (hf.co/org/repo:Q4_K_M) and uvicorn decodes %2F before routing."""
    try:
        ollama_client.delete_model(name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # A persisted composer override pointing at a model that no longer
    # exists would fail every chat turn, restart or not — drop it.
    if settings.get("chat_model") in {name, name.removesuffix(":latest")}:
        settings.update(chat_model=None)
    return {"status": "ok"}
