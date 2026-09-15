"""Provider routes (Phase 21): list/create/update/delete providers,
activate one, resolve the current routing, and build a recommended
provider from the benchmark leaderboard."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import bench
import ollama_client
import providers

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderInfo(BaseModel):
    name: str
    description: str
    routes: dict[str, str]
    options: dict[str, dict]
    builtin: bool


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]
    active: str
    roles: list[str]
    resolved: dict[str, str | None]


class ProviderWriteRequest(BaseModel):
    name: str
    description: str = ""
    routes: dict[str, str]
    options: dict[str, dict] = {}


class RecommendRequest(BaseModel):
    name: str = "recommended"
    save: bool = False


def _info(p: providers.Provider) -> ProviderInfo:
    return ProviderInfo(**p.to_dict())


def _resolved() -> dict[str, str | None]:
    return {role: providers.resolve(role) for role in providers.ROLES}


def _response() -> ProvidersResponse:
    return ProvidersResponse(
        providers=[_info(p) for p in providers.discover()],
        active=providers.active().name,
        roles=list(providers.ROLES),
        resolved=_resolved(),
    )


@router.get("", response_model=ProvidersResponse)
def list_providers() -> ProvidersResponse:
    return _response()


@router.post("", response_model=ProvidersResponse)
def create_provider(request: ProviderWriteRequest) -> ProvidersResponse:
    try:
        providers.save(
            request.name, request.description, request.routes, request.options
        )
    except providers.ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response()


@router.put("/{name}", response_model=ProvidersResponse)
def update_provider(name: str, request: ProviderWriteRequest) -> ProvidersResponse:
    if request.name != name:
        raise HTTPException(
            status_code=400, detail="Path name and body name must match."
        )
    return create_provider(request)


@router.delete("/{name}", response_model=ProvidersResponse)
def delete_provider(name: str) -> ProvidersResponse:
    try:
        providers.delete(name)
    except providers.ProviderError as exc:
        status = 404 if "No such" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return _response()


@router.post("/{name}/activate", response_model=ProvidersResponse)
def activate_provider(name: str) -> ProvidersResponse:
    try:
        providers.activate(name)
    except providers.ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _response()


@router.post("/recommend", response_model=ProviderInfo)
def recommend_provider(request: RecommendRequest) -> ProviderInfo:
    """Compose the strongest provider from measured benchmark results
    (providers.recommend over bench.leaderboard, restricted to installed
    models). `save` persists it under `name`; otherwise it's a preview."""
    installed = {m["name"] for m in ollama_client.list_models()}
    try:
        recommended = providers.recommend(bench.leaderboard(), installed=installed)
        if request.save:
            recommended = providers.save(
                request.name, recommended.description, recommended.routes
            )
    except providers.ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _info(recommended)
