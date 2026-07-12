# Local AI Assistant

## Project
Local Ollama-based assistant with chat, PDF tools, and RAG. No cloud APIs.
See `plan.md` for current phase and task status. Read it at the start of every session.

## Stack
- Python 3.11+ backend (FastAPI/uvicorn), React/TypeScript frontend (Vite + Tailwind, in `web/`)
- Ollama at `localhost:11434` — thin API wrapper only, no business logic in `ollama_client.py`
- pdfplumber (read), pypdf (fill AcroForm fields)
- ChromaDB for local vector store, nomic-embed-text for embeddings
- Primary models: qwen2.5 or llama3.1 (both support tool-calling)

## Commands
```bash
uvicorn server:app --reload --port 8000    # backend API (also serves web/dist if built)
cd web && npm run dev                      # frontend dev server (localhost:5173, proxies /api to :8000)
cd web && npm run build && npm run lint    # production build + typecheck/lint
pytest tests/ -v          # fast, mocked, no live model
pytest -m e2e -v          # live model required; skips cleanly if Ollama is down
ruff check . && ruff format .
```

## Key rules
- All Ollama calls go through `ollama_client.py` — nowhere else
- Tool dispatch lives in `agent.py` only — add new tools by adding a function in `tools/` and a case in `_execute_tool()`
- The second way to add a tool: a skill (`skills.py`) — a directory under `skills/<name>/` with `skill.yaml` + `prompt.md` or `run.py`, discovered fresh every turn, no code change needed. See `skills/README.md`. The model's own `create_skill` tool can only write instruction skills (`prompt.md`), never code (`run.py`) — that boundary is structural, not a convention, and must stay that way.
- Conversation history source of truth is `memory.py`, held server-side in `server.py` — the frontend never owns assistant state, it re-fetches after each mutation
- Model name comes from env var `OLLAMA_MODEL` by default, overridable per-session via `POST /api/settings/model` — never hardcoded
- Use `pathlib.Path` for all file I/O
- Frontend HTTP calls go through `web/src/api.ts` — nowhere else (the frontend's version of the thin-wrapper rule)

## Gotchas
- pypdf silently succeeds on non-form PDFs without writing — always call `get_fields()` first
- ChromaDB returns distances not scores — lower = more similar, don't invert the sort
- Tool call + result pairs in message history must be kept together — never trim one without the other
- `server.py`'s static-file mount for `web/dist` must stay the LAST route registered — Starlette matches in registration order, and a `/` mount would shadow every `/api/*` route above it

## Workflow

### 1. Read the plan first
Before starting any work, read `plan.md`. Mark tasks complete as you go. If a task turns out to need splitting, update the plan before diving in.

### 2. Verify against a real Ollama call before scaling out
For any new tool or prompt-shape change, run it against the live model once and inspect the raw request/response before wiring it into the full agent loop or writing tests around assumed behavior. Don't code to memory of the API — verify the current shape.

### 3. Demand elegance (balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

## Choices
- Don't ever add yourself as co-author
- Prefer editing existing files over creating new ones
- Remove debug print statements before marking a task done
