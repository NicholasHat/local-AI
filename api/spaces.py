"""Shared communication space routes (Phase 20). A human posts through
here with author "user"; agents post through the post_to_space tool."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import spaces

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


class SpaceSummary(BaseModel):
    id: str
    name: str
    purpose: str
    created_at: str
    updated_at: str
    post_count: int


class SpacePost(BaseModel):
    id: str
    ts: str
    author: str
    content: str


class SpaceDetail(BaseModel):
    id: str
    name: str
    purpose: str
    created_at: str
    updated_at: str
    posts: list[SpacePost]


class CreateSpaceRequest(BaseModel):
    name: str
    purpose: str = ""


class PostRequest(BaseModel):
    content: str
    author: str = "user"


def _summary(meta: spaces.SpaceMeta) -> SpaceSummary:
    return SpaceSummary(**meta.__dict__)


def _detail(raw: dict) -> SpaceDetail:
    return SpaceDetail(**raw)


@router.get("", response_model=list[SpaceSummary])
def list_spaces() -> list[SpaceSummary]:
    return [_summary(m) for m in spaces.list_recent()]


@router.post("", response_model=SpaceDetail)
def create_space(request: CreateSpaceRequest) -> SpaceDetail:
    try:
        return _detail(spaces.create(request.name, request.purpose))
    except spaces.SpaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{space_id}", response_model=SpaceDetail)
def get_space(space_id: str) -> SpaceDetail:
    try:
        return _detail(spaces.get(space_id))
    except spaces.SpaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{space_id}/posts", response_model=SpacePost)
def post_to_space(space_id: str, request: PostRequest) -> SpacePost:
    try:
        return SpacePost(**spaces.post(space_id, request.author, request.content))
    except spaces.SpaceError as exc:
        missing = "No such space" in str(exc) or "Invalid space id" in str(exc)
        status = 404 if missing else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/{space_id}")
def delete_space(space_id: str) -> dict:
    try:
        spaces.delete(space_id)
    except spaces.SpaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}
