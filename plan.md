# Implementation Plan — Local AI Assistant

A local, private assistant built on Ollama with a tool-calling agent loop, PDF
read/fill tools, and RAG over local documents. No cloud APIs. See `CLAUDE.md`
for the pinned stack and hard rules — this plan sequences the build.

## Guiding principle

Build a **walking skeleton first**, then fan out. The tool-calling loop is the
heart of the app; everything else is scaffolding around it. Prove the full
cycle (prompt → model requests tool → we execute → feed result back → final
answer) end-to-end with a dummy tool *before* writing any real tool.

Phases are ordered by dependency, not by module. Each phase has a
**definition of done** — the phase isn't finished until that round-trips.

---

## Key decisions (named up front, not left implicit)

1. **Native Ollama tool-calling, not prompt-parsed JSON.**
   Use `/api/chat` with a `tools=[...]` schema; read tool requests from
   `message.tool_calls` in the response. This is more robust than regex-parsing
   model content. It dictates the `memory.py` message schema (a `tool` role,
   linking results back to the originating call), so it is **not deferrable**.
   → **Verify the exact Ollama request/response shape from current docs in
   Phase 1** — code to the docs, not to memory. That shape is the spine of both
   the agent loop and the history format.

2. **Non-streaming first.** Streaming + tool-calling together is fiddly. Get the
   loop correct with full responses; add token streaming as a later enhancement.
   This is a deliberate decision, not an omission.

3. **Max-iteration guard on the tool loop.** The model can chain tool calls; the
   loop runs until a response comes back with no `tool_calls`. It needs a hard
   ceiling (e.g. 8 iterations) to prevent runaway/infinite loops.

4. **The thin-wrapper rule is the test seam.** Because all Ollama traffic goes
   through `ollama_client.py`, `agent.py` and `tools/` are unit-tested against a
   **mocked client** — no live model needed for `pytest tests/`. This is the
   payoff of the architecture rule; the plan leans on it.

5. **`doc_search` is a tool the model calls**, not context auto-injected before
   the model runs. This matches `CLAUDE.md` (tool dispatch, `doc_search` in
   `tools/`). The model decides when a query needs document lookup.

6. **RAG is two separate flows:** *ingest* (chunk → embed → store) and *retrieve*
   (embed query → search). Ingestion is triggered by file upload in the UI;
   retrieval happens inside the `doc_search` tool.

---

## Phase 1 — Scaffold

Project skeleton and tooling. No app logic.

- `pyproject.toml` (or `requirements.txt`): streamlit, ollama, pdfplumber,
  pypdf, chromadb, python-dotenv, pytest, ruff.
- Directory layout per `CLAUDE.md`: `ollama_client.py`, `agent.py`, `memory.py`,
  `ui.py`, `tools/`, `tests/`.
- `.env` loading for `OLLAMA_MODEL` (never hardcode the model name).
- ruff config; empty `tests/` with one passing sanity test.
- **Verify Ollama's `/api/chat` tool-calling request/response schema from
  current docs** and capture it as a note/fixture for later phases.

**Done when:** `ruff check .` passes and `pytest tests/ -v` runs green.

## Phase 2 — `ollama_client.py` (thin wrapper)

The single choke point for all Ollama traffic.

- `chat(messages, tools=None, model=...)` → returns the raw message (including
  `tool_calls` when present).
- `embed(text)` → wraps nomic-embed-text. **Do not forget this** — the
  "all Ollama calls go through here" rule includes embeddings, and it's the RAG
  dependency.
- Health-check helper for the UI to call at startup.
- No business logic — just HTTP/SDK calls and response passthrough.

**Done when:** `chat()` returns a real completion and `embed()` returns a vector
against a running Ollama (a quick live smoke test / script).

## Phase 3 — Agent loop + memory (walking skeleton)

The core. Build with **one dummy tool** (e.g. `get_time`) to prove the cycle.

- `memory.py`: conversation history is the source of truth (not Streamlit
  session state). Message schema supports `tool` role and links tool
  results to their originating call. **Tool call + its result must be kept
  together** — never trim one without the other.
- `agent.py`: the loop —
  `send history → model returns tool_calls? → _execute_tool() each → append
  results → repeat → until no tool_calls → return final answer`.
  Includes the **max-iteration guard**.
- `_execute_tool(name, args)`: the single dispatch point. New tools = new
  function in `tools/` + new case here.

**Done when:** a prompt that forces the dummy tool round-trips end-to-end via
`pytest` against a **mocked `ollama_client`** — no live model.

## Phase 4 — Real tools

Each tool = a function in `tools/` + a case in `_execute_tool()`. Unit-tested
against sample PDFs, no live model.

- `tools/pdf_reader.py` — extract text/fields with pdfplumber.
- `tools/pdf_filler.py` — fill AcroForm fields with pypdf.
  **Always call `get_fields()` first** — pypdf silently succeeds on non-form
  PDFs without writing; detect and report that case instead.
- `tools/doc_search.py` — the retrieve half of RAG (embed query → Chroma
  search). **Chroma returns distances, not scores** — lower = more similar;
  sort ascending, don't invert.

**Done when:** each tool has passing unit tests, and the agent can invoke each
via `_execute_tool()`.

## Phase 5 — RAG ingestion

The *ingest* flow, separate from retrieval.

- Chunk documents → `embed()` each chunk → store in ChromaDB with metadata.
- Invoked from the UI on file upload.
- Ingest and retrieve share the collection but are distinct code paths.

**Done when:** uploading a doc makes its content findable via the `doc_search`
tool in a real conversation.

## Phase 6 — Streamlit UI

Wire it together last.

- Chat interface backed by `memory.py` (not `st.session_state` as source of
  truth).
- File upload → triggers Phase 5 ingestion.
- **Wrap expensive init (ChromaDB client, Ollama health check) in
  `@st.cache_resource`** — otherwise Streamlit reruns it every interaction.
- Startup health check via `ollama_client`.

**Done when:** `streamlit run ui.py` gives a working chat that can answer,
search uploaded docs, and read/fill a PDF — all through the agent loop.

## Key decisions for Phases 7–12 (planned 2026-07-12)

1. **Backend server: FastAPI + uvicorn.** Pydantic request/response models give
   a typed API contract, `TestClient` gives cheap contract tests, and native
   async + SSE support means streaming can be layered on later without a
   framework change. A new `server.py` (plus `api/` if it grows) wraps the
   existing modules — `agent`, `memory`, `ingest`, `vectorstore` stay untouched
   and remain the source of truth. The frontend never talks to Ollama directly.

2. **Frontend: Vite + React + TypeScript + Tailwind, in `web/`.** Not Next.js —
   this is a single-user local app with no SSR, SEO, or server-component needs;
   Vite keeps the toolchain small and the dev loop fast. One-page app shell:
   sidebar (documents, model picker, skills, status) + transcript + composer.

3. **E2E tests are a separate pytest marker.** `tests/e2e/` marked
   `@pytest.mark.e2e`, excluded by default (`addopts = -m "not e2e"`), run
   explicitly with `pytest -m e2e`. A session fixture calls
   `ollama_client.health_check()` and **skips (not fails)** the whole suite when
   Ollama is down. Unit tests stay mock-only and fast — that separation is the
   payoff of the thin-wrapper rule and must survive the migration.

4. **Conversation state stays server-side, one active conversation.** The API
   holds a module-level `Conversation` (same as `ui.py` does today via session
   state). Multi-conversation/persistence remains a later enhancement — don't
   let the migration smuggle in scope.

5. **Model selection is a per-request override, defaulting to `OLLAMA_MODEL`.**
   `agent.run()` and `ollama_client.chat()` already support/thread a `model`
   param (chat does; run needs one). The env var stays the default — the rule
   "model name never hardcoded" is unchanged; the UI just picks from what the
   local Ollama actually has installed.

6. **Skills are files on disk, discovered at runtime** — `skills/<name>/` with a
   `skill.yaml` manifest and either a `prompt.md` (instruction skill) or
   `run.py` (code skill). They surface to the model as ordinary tools: the
   loader converts manifests into entries appended to `TOOL_SCHEMAS`, and
   `_execute_tool()` gains exactly one new case that routes `skill__*` names to
   the skills registry. This keeps the CLAUDE.md rule "tool dispatch lives in
   agent.py only" true — the registry executes, agent.py still dispatches.

---

## Phase 7 — E2E test harness over the current tools

Prove every existing tool works end-to-end against a **live model** before any
architecture moves. This is the safety net for the whole migration: after
Phase 8+ the same suite reruns through the HTTP API instead of direct calls.

- `tests/e2e/` + `e2e` marker + auto-skip fixture (decision 3). Register the
  marker in `pyproject.toml` and exclude it from the default run.
- Test fixtures: a small text-based PDF and an AcroForm PDF checked into
  `tests/fixtures/` (generate the AcroForm one with pypdf in a fixture script
  if none exists yet).
- One E2E test per tool, each driving `agent.run()` with a natural-language
  prompt that should force the tool, then asserting on the transcript
  (`conversation.messages`) that the tool was actually called AND the final
  answer reflects its result:
  - `get_time` — "what time is it in UTC?"
  - `read_pdf` — summarize the fixture PDF by path.
  - `list_pdf_fields` + `fill_pdf` — list fields, fill one, then re-read the
    output file with pypdf to assert the value landed. Also assert the
    non-form-PDF case reports clearly instead of silently succeeding.
  - ingestion + `search_documents` — ingest a fixture doc into a **temporary
    Chroma path** (point `CHROMA_PATH` at `tmp_path` via monkeypatch), ask a
    question only that doc answers.
  - `read_uploaded_document` — upload-dir variant of the same.
- E2E runs must not touch the real `chroma/` or `uploads/` dirs — always
  redirect via env/monkeypatch to temp dirs.
- Model-behavior assertions must be **loose** (tool was called, key fact in
  answer) — never string-match model prose exactly, or the suite will flake.

**Done when:** with Ollama running and `OLLAMA_MODEL` set, `pytest -m e2e -v`
passes; with Ollama stopped, the suite skips cleanly; the default
`pytest tests/` run is unchanged (47 tests, no live calls).

## Phase 8 — API extraction (FastAPI)

Put an HTTP boundary around the existing backend. Streamlit keeps working
untouched until Phase 12 — the two shells coexist during the migration.

- `server.py`: FastAPI app + uvicorn entrypoint (`uvicorn server:app`).
  Endpoints (pydantic models for every request/response):
  - `GET  /api/health` — Ollama reachability + configured model.
  - `GET  /api/conversation` — full transcript incl. tool-role messages (the
    frontend renders tool events from these).
  - `POST /api/chat` — `{message}` → runs `agent.run()` → `{reply}`.
    Non-streaming, exactly today's behavior.
  - `POST /api/conversation/reset`
  - `POST /api/upload` — multipart; save to upload dir, run `ingest`, append
    the same system note `ui.py` adds today; returns chunk count.
  - `GET  /api/documents` — what's been uploaded/ingested.
- Startup does the health check once (the `@st.cache_resource` gotcha becomes
  a FastAPI lifespan/startup hook).
- CORS for the Vite dev origin (`localhost:5173`) only.
- Contract tests in `tests/test_api.py` with `TestClient` and a **mocked
  ollama_client** — same seam as the agent tests, no live model.
- Re-point the Phase 7 E2E suite: add an API-level variant (or parametrize)
  so chat/upload/search round-trip through HTTP against live Ollama.

**Done when:** contract tests pass mocked; `pytest -m e2e` passes through the
HTTP layer with Ollama up; Streamlit UI still fully works.

## Phase 9 — React frontend

Build in `web/` against the Phase 8 API. Parity first, polish second — same
discipline as the original walking skeleton.

**9a — Working shell (parity):**
- Vite + React + TS scaffold; typed API client module mirroring the pydantic
  contract (single fetch wrapper — the frontend equivalent of the thin-wrapper
  rule).
- App shell: sidebar + transcript + composer. Send/receive chat, upload with
  progress state, reset, health indicator. Distinct rendering for user,
  assistant, and **tool-event cards** (name + collapsed args/result) — tool
  use is visible, not hidden in logs.
- Error states: Ollama down, upload failure, model error — shown inline, not
  swallowed.

**9b — Product polish:**
- Deliberate visual system per `docs/ui-move-plan.md`: strong type scale,
  ample whitespace, calm surfaces; first-run/empty state designed, not
  defaulted. Markdown rendering (+ code blocks) for assistant messages.
- Responsive layout; sidebar collapses on narrow viewports.
- Document panel shows ingested docs with chunk counts.

**Done when:** every current Streamlit capability works from the React app,
checked against the Phase 7/8 E2E flows manually; `npm run build` produces a
production bundle the backend can serve (or that runs standalone).

## Phase 10 — Model selection

- `ollama_client.list_models()` — thin wrapper over the SDK's `list()`
  (traffic rule: it goes through ollama_client like everything else). Include
  each model's capabilities so the UI can mark models that lack tool-calling
  support (qwen2.5 and llama3.1 both have it; embed models don't).
- Thread a `model: str | None` override through `agent.run()` →
  `ollama_client.chat()`; default remains `config.get_model()`.
- `GET /api/models` + model field on `POST /api/chat` (or a
  `PUT /api/settings/model` if per-conversation feels cleaner — implementer's
  call, but the chosen model must live server-side with the conversation, not
  only in React state).
- Sidebar model picker: current model, dropdown of installed models,
  tool-capable badge; switching mid-conversation is allowed (history format is
  model-agnostic).
- Unit tests mocked; one E2E test that chats via a second installed model if
  more than one is available (skip otherwise).

**Done when:** the UI lists real installed models, switching changes which
model answers (verify via `/api/health` or response metadata), and unset
`OLLAMA_MODEL` still fails loudly as designed.

## Phase 11 — Skills system

User-authorable capabilities the model can call, without editing Python for
the common case. File format (decision 6):

```
skills/
  summarize-for-email/
    skill.yaml      # name, description, parameters (JSON-schema properties)
    prompt.md       # instruction skill: rendered with {args}, returned as the
                    # tool result — the model follows the instructions
  word-count/
    skill.yaml
    run.py          # code skill: defines run(**args) -> str
```

- `skills.py` (registry): discover `skills/*/skill.yaml`, validate manifests,
  build tool schemas named `skill__<name>`, execute by rendering `prompt.md`
  (simple `str.format`-style substitution) or importing and calling
  `run.py:run()`. Malformed skills are reported and skipped, never crash the
  loop. Reload on each agent turn — skills are small, and hot reload beats a
  restart requirement.
- `agent.py`: append registry schemas to the advertised tools; **one** new
  dispatch case routing `skill__*` to the registry. Update the CLAUDE.md
  tool-adding rule to mention skills as the second path.
- Code skills run in-process. This is a local, single-user, user-authored-only
  trust model — document that plainly in the skills README; no sandboxing
  theater.
- API: `GET /api/skills`, `POST /api/skills` (create from name/description/
  parameters/body), `PUT /api/skills/{name}`, `DELETE /api/skills/{name}`.
  Path-traversal-safe: skill names validated to a slug pattern before touching
  the filesystem.
- UI: skills panel in the sidebar — list, create, and edit skills with a
  simple form + textarea editor. Creating an instruction skill must be
  possible entirely from the browser.
- Self-authoring: a built-in `create_skill` tool so the assistant itself can
  write an instruction skill when the user asks it to ("make yourself a skill
  that…"). It goes through the same validated registry write path as the API.
- Ship one example skill of each type as living documentation.
- Tests: registry unit tests (discovery, validation, both execution paths,
  bad-manifest handling, name validation); one E2E test where a prompt
  triggers an example skill through the live model.

**Done when:** a skill created in the browser is callable by the model in the
next message, `create_skill` round-trips ("create a skill that X" → skill file
exists → model uses it), and all tests pass.

## Phase 12 — Cutover and cleanup

- Serve the built React app from FastAPI (static mount) so the whole product
  is one process: `uvicorn server:app` → browse to it.
- Delete `ui.py` and the streamlit dependency; drop Streamlit-specific gotchas
  from CLAUDE.md and add the new commands (`uvicorn server:app`, `cd web &&
  npm run dev`, `pytest -m e2e`).
- Full pass: `ruff check .`, `pytest tests/`, `pytest -m e2e` (Ollama up),
  `npm run build`, manual smoke of every tool from the browser.

**Done when:** the Streamlit code is gone and everything in the Phase 7 E2E
suite plus skills/model-selection works from the React UI.

---

## Later enhancements (explicitly out of scope for v1)

- Token streaming in the UI via SSE (the FastAPI choice keeps this cheap).
- OCR + overlay for scanned/non-AcroForm PDFs (harder; form fields first).
- Multiple concurrent conversations / persisted history across sessions.
- Sandboxed execution for code skills (only if skills ever come from anywhere
  other than the local user).
