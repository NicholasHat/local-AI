# Local AI Assistant

## Project
Local Ollama-based assistant with chat, PDF tools, RAG, agentic workflows,
shared agent spaces, projects, model benchmarks/arena, provider routing, a
model catalog + vault, and a sandboxed coding agent. No cloud AI APIs — the
network is used only to discover/fetch models and read public pages, never
for inference. See `plan.md` for current phase and task status. Read it at
the start of every session.

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
- Tool dispatch for the **chat** agent lives in `agent.py` only — add new tools by adding a function in `tools/` and a case in `_execute_tool()`
- The second way to add a chat tool: a skill (`skills.py`) — a directory under `skills/<name>/` with `skill.yaml` + `prompt.md` or `run.py`, discovered fresh every turn, no code change needed. See `skills/README.md`. The model's own `create_skill` tool can only write instruction skills (`prompt.md`), never code (`run.py`) — that boundary is structural, not a convention, and must stay that way.
- The **coding agent** (`coding_agent.py`) is a deliberately separate loop with its own `_execute_coding_tool()` dispatch and a smaller tool set (list/read/write files + run tests), confined to a throwaway `git worktree`. It is never merged into `agent.py`'s dispatch and never exposed as a chat tool — it only starts from an explicit human action on the Coding page. This keeps the chat model, which reads untrusted documents and search results, structurally unable to trigger code execution. See `plan.md`'s Phase 16–18 decisions for the full reasoning.
- Conversation history source of truth is `memory.py`, held server-side in `server.py` — the frontend never owns assistant state, it re-fetches after each mutation
- Model name comes from env var `OLLAMA_MODEL` by default, overridable per-session via `POST /api/settings/model` — never hardcoded
- Use `pathlib.Path` for all file I/O
- Frontend HTTP calls go through `web/src/api.ts` — nowhere else (the frontend's version of the thin-wrapper rule)
- **Model resolution** is `providers.resolve(role, override)` everywhere a model is needed (chat, coding, workflow steps, arena judge): explicit override → session chat override (`settings.json`) → active provider route → env default. Never read `OLLAMA_MODEL` directly outside `config.py`
- **Workflows** (`workflows.py`, `workflows/<name>.yaml`) run steps through `agent.run(..., tools=[allowlist])` — they can only reach chat tools, never the coding loop. Inter-step/inter-model communication goes through a shared space (`spaces.py`) via the `read_space` / `post_to_space` chat tools; the runner auto-posts each step's output there
- **Long-running work** (bench, arena, workflow runs) uses `jobstore.py` (`jobs/<kind>/<id>.json`) and is served by `api/jobs.py` (get + SSE events). Coding runs keep their own `runs.py`. New domains get an `APIRouter` in `api/<domain>.py`, included in `server.py` before the static mount
- **Benchmarks are deterministic**: `benchmarks/suite.yaml` tasks have mechanical checks only; coding tasks are checked by shape/known output and never execute model output. A judge model is only used in the ad-hoc arena
- **The vault** (`vault.py`) copies Ollama's manifest + blobs to a plain directory (`MODEL_VAULT_DIR`) and restores them without the registry — that is the insurance against upstream models disappearing. `catalog.yaml` is a dated seed; currency comes from the Hugging Face trending feed and registry manifest checks in `catalog.py`, both optional and offline-tolerant
- Runtime state dirs are all gitignored file stores: `conversations/ runs/ jobs/ spaces/ projects/ providers/ bench_results/ settings.json`

## Gotchas
- pypdf silently succeeds on non-form PDFs without writing — always call `get_fields()` first
- ChromaDB returns distances not scores — lower = more similar, don't invert the sort
- Tool call + result pairs in message history must be kept together — never trim one without the other
- `server.py`'s static-file mount for `web/dist` must stay the LAST route registered — Starlette matches in registration order, and a `/` mount would shadow every `/api/*` route above it
- Ollama durations (`total_duration`, `eval_duration`, ...) are nanoseconds; `list_models()`'s `digest` is sha256 of the local manifest bytes and the registry manifest endpoint returns those same bytes with no digest header — compare by hashing the body
- DuckDuckGo's HTML endpoint rate-limits and serves a bot challenge readily; `tools/web.py` falls through to Wikipedia and reports which backend answered. Set `SEARXNG_URL` for robust search
- Model names contain `:` and `/` (`hf.co/org/repo:Q4_K_M`) — API path params for them must use `{name:path}`

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
