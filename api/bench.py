"""Benchmark, leaderboard, and arena routes (Phase 22). Runs are jobs:
history and live events come from /api/jobs/bench|arena/... (api/jobs.py);
this router only knows how to start them and serve stored results."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import bench
from api.jobs import JobResponse, job_response

router = APIRouter(prefix="/api/bench", tags=["bench"])


class SuiteTask(BaseModel):
    id: str
    category: str
    prompt: str
    check_type: str
    expected: str


class SuiteResponse(BaseModel):
    version: int
    tasks: list[SuiteTask]


class StartBenchRequest(BaseModel):
    model: str
    options: dict = {}


class LeaderboardRow(BaseModel):
    model: str
    tool_capable: bool
    overall: float
    categories: dict[str, float]
    tokens_per_sec: float | None
    load_seconds: float | None
    ran_at: str
    suite_version: int


class BenchResult(LeaderboardRow):
    tasks: list[dict]


class StartArenaRequest(BaseModel):
    prompt: str
    models: list[str]
    judge: str | None = None
    options: dict = {}


@router.get("/suite", response_model=SuiteResponse)
def get_suite() -> SuiteResponse:
    try:
        suite = bench.load_suite()
    except bench.BenchError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return SuiteResponse(
        version=suite["version"],
        tasks=[
            SuiteTask(
                id=t["id"],
                category=t["category"],
                prompt=t["prompt"],
                check_type=t["check"]["type"],
                expected=bench.expected_text(t["check"]),
            )
            for t in suite["tasks"]
        ],
    )


@router.post("/runs", response_model=JobResponse)
def start_bench(request: StartBenchRequest) -> JobResponse:
    try:
        job = bench.start(request.model, request.options or None)
    except bench.BenchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_response(job)


@router.get("/results", response_model=list[LeaderboardRow])
def leaderboard() -> list[LeaderboardRow]:
    return [LeaderboardRow(**row) for row in bench.leaderboard()]


@router.get("/results/{model:path}", response_model=BenchResult)
def get_result(model: str) -> BenchResult:
    try:
        return BenchResult(**bench.result(model))
    except bench.BenchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/arena", response_model=JobResponse)
def start_arena(request: StartArenaRequest) -> JobResponse:
    try:
        job = bench.start_arena(
            request.prompt, request.models, request.judge, request.options or None
        )
    except bench.BenchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_response(job)
