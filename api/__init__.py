"""HTTP routers, one per domain (plan.md decision 10, Phases 19–26). Each
module exposes `router = APIRouter(prefix="/api/<domain>")`; server.py
includes them before its static mount, which must stay last."""
