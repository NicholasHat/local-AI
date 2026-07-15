# Implementation Plan — Local AI Assistant

A local, private assistant built on Ollama with a tool-calling agent loop, PDF
read/fill tools, and RAG over local documents. No cloud APIs. See `CLAUDE.md`
for the pinned stack and hard rules — this plan sequences the build.

**Status (2026-07-15): Phases 1–15 complete.** Plus a Perplexity-style React
redesign (denim-blue/gray/white theme, autosizing composer, inline model
picker, a standalone Skills page, and a tool-activity log panel — not
separately phased, done as a direct UI request). The app is FastAPI + React
(`web/`), with model selection, a file-based skills system, persisted
multi-conversation history, document removal, and pulling additional models
from the browser. The Streamlit UI (Phase 6) has been fully cut over and
removed (Phase 12). See each phase's "Done when" line for what was verified.
Next work is whatever comes after the "Later enhancements" list below, or a
fresh ask.

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

## Key decisions for Phases 13–15 (planned 2026-07-15)

1. **Documents (Phase 13) before history (Phase 14) before model pulling
   (Phase 15).** Deletion is the smallest, lowest-risk change and exercises
   `vectorstore.py`'s delete path that Phase 14 doesn't need but is good to
   have proven first. History is the largest architectural change (the
   single-conversation assumption threaded through `server.py` and the
   frontend). Model pulling is independent of the other two and can slot in
   any time after — ordered last because it introduces this app's first
   streaming endpoint, the highest-risk primitive of the three.

2. **Conversations are JSON files, not a database.** Consistent with this
   project's existing file-based patterns (`skills/<name>/`, uploaded PDFs
   under `uploads/`) rather than introducing SQLite or another new
   dependency for what's a handful of small, human-readable records. A new
   `conversations.py` (mirrors `skills.py`'s discover/load/save shape) owns
   `conversations/<id>.json` — each file holds `{id, title, created_at,
   updated_at, messages}`. `conversations/` gets gitignored alongside
   `uploads/` and `chroma/`.

3. **`GET /api/conversation` and `POST /api/conversation/reset` are
   replaced, not deprecated-in-place.** Once conversations persist, "the one
   active conversation" becomes "the currently active conversation among
   many" — keeping the old singular endpoints around as a compatibility
   shim would contradict CLAUDE.md's "no backwards-compat hacks" rule. The
   frontend's `handleNewChat` moves from resetting the one conversation to
   creating a new one via the Phase 14 endpoints.

4. **Model pulling reuses SSE**, the same streaming primitive already
   earmarked for token streaming in "Later enhancements" below — pull
   progress is the first real use of it, ahead of chat streaming, but the
   plumbing (a `StreamingResponse` route) is the same shape either way.

5. **No new frontend dependencies for any of the three.** History gets a
   plain list in the existing `Sidebar`; the model manager extends the
   existing composer-adjacent `ModelPicker` area. No router, no state
   library — same posture as the existing app.

---

## Phase 13 — Remove attached documents

Small, self-contained: a document uploaded via the sidebar can currently
never be un-attached short of restarting with a fresh `uploads/`/`chroma/`.

- `vectorstore.py`: add `delete_by_source(source: str) -> None` —
  `get_collection().delete(where={"source": source})`. Mirrors `add`/`query`
  as a thin Chroma passthrough.
- `server.py`: `DELETE /api/documents/{filename}` — path-traversal-safe
  (reject any filename where `Path(filename).name != filename`, same
  discipline as the Phase 11 skills-name validation), delete the file from
  `config.get_upload_dir()`, call `vectorstore.delete_by_source(filename)`,
  404 if the file doesn't exist.
- `web/src/api.ts`: add `deleteDocument(filename)`. `Sidebar.tsx`: a ✕
  button per document row (same pattern already used for skills deletion),
  wired through `App.tsx`'s existing `refreshDocuments` flow.
- Tests: `vectorstore.delete_by_source` against a temp Chroma path (real
  Chroma, no mock needed — it's fast); API contract test mocked; a
  path-traversal rejection test (`../../etc/passwd` etc.).

**Done when:** uploading a PDF, deleting it from the sidebar, and then
asking a question that only that PDF could answer shows `search_documents`
finds nothing — proving both the file and its embedded chunks are gone, not
just the sidebar row.

## Phase 14 — Persisted, multi-conversation history

The biggest of the three. Today's `server.py` holds one module-level
`Conversation` that "New chat" wipes — there is no way to go back.

- `conversations.py` (new registry, file-based per decision 2 above):
  - `create() -> ConversationMeta` — new empty conversation, `id` (e.g.
    `uuid4().hex[:12]`), `title=None`, timestamps.
  - `save(id, conversation: Conversation)` — writes `conversations/<id>.json`
    (messages via `conversation.messages`, per `memory.py`'s existing
    `Conversation` class, unchanged). Sets `title` from the first user
    message (truncated ~40 chars) the first time it's non-empty; title is
    static after that — no extra model call to summarize it.
  - `load(id) -> Conversation` — reconstructs a `memory.py` `Conversation`
    from the stored messages.
  - `list_recent(limit=20) -> list[ConversationMeta]` — `{id, title,
    updated_at}` sorted newest first; this is the "short list" the sidebar
    renders.
  - `delete(id)` — removes the file.
- `server.py`: replace the single `_conversation` global with
  `_active_conversation_id`, loading/saving via `conversations.py` around
  each mutation (`/api/chat`, `/api/upload`'s system note). Small
  conversations, no in-memory caching needed — load-modify-save per request
  is simple and correct.
  - `GET /api/conversations` → the short history list.
  - `POST /api/conversations` → create + activate a new one (replaces
    `/api/conversation/reset`'s role as "New chat").
  - `POST /api/conversations/{id}/activate` → switch the active
    conversation.
  - `GET /api/conversation` stays as-is in shape (returns the *active*
    conversation's messages) so `Transcript` doesn't need to change how it
    fetches — only which conversation backs it.
  - `DELETE /api/conversations/{id}` → remove a past chat; if it was active,
    fall back to the most recent remaining one (or create a fresh one if
    none remain).
- Frontend: `Sidebar.tsx` gains a "History" list below the Chat/Skills nav —
  title + relative timestamp, click to activate + refresh the transcript, ✕
  to delete (same pattern as Documents/Skills). "New chat" now calls
  `POST /api/conversations` instead of the old reset endpoint.
- Tests: `conversations.py` unit tests (create/list/load/delete, JSON
  round-trip, title truncation); API contract tests mocked; one test that
  reloads a fresh `conversations.py`/`Conversation` from disk mid-test
  (simulating a backend restart) and confirms history survives — this is
  the actual point of persisting, so it must be asserted, not assumed.

**Done when:** starting a new chat preserves the previous one in a visible
history list, clicking a past chat restores its exact transcript, deleting
one removes it from disk, and restarting `uvicorn` still shows the same
history (proves persistence, not just in-memory state).

## Phase 15 — Pull additional local models

Today's model picker only lists models already pulled. This adds the other
half: getting new ones onto the machine from the browser.

- `ollama_client.py`: `pull_model(name: str)` — thin wrapper around the SDK's
  `client.pull(model=name, stream=True)`, yielding normalized progress dicts
  (`status`, `completed`, `total`) as they arrive. Still just passthrough —
  no retry/business logic, per the thin-wrapper rule. Add `delete_model(name)`
  too (`client.delete()`) so models can be removed as well as added.
- `server.py`:
  - `GET /api/models/library` — a small curated static list of recommended
    tags (e.g. `qwen2.5`, `llama3.1`, `mistral`, `gemma2`, `phi3`), each
    flagged tool-capable or not from the same knowledge already encoded for
    installed models. Ollama has no public model-search API, so this is a
    hand-maintained list, not a live catalog — the user can also type an
    arbitrary tag outside the curated set.
  - `POST /api/models/pull` — `{name}`, `StreamingResponse` (SSE,
    `text/event-stream`) forwarding `pull_model`'s progress events to the
    client. This app's first streaming route (decision 4 above).
  - `DELETE /api/models/{name}` → `ollama_client.delete_model`.
- Frontend: extend the composer-adjacent model area with an "+ Add model"
  affordance — pick from the curated list or type a tag, a progress bar
  fed by the SSE stream, refresh `GET /api/models` on completion. Per-model
  ✕ (delete) alongside it. No new state library — an `EventSource` or
  `fetch` + `ReadableStream` read loop is enough.
- Tests: `pull_model`/`delete_model` unit tests against a mocked client
  (assert passthrough of streamed chunks); API test mocked. A live E2E pull
  is impractical in CI (multi-GB downloads) — add one under `@pytest.mark.e2e`
  but gate it behind an explicit opt-in env var (e.g. `RUN_MODEL_PULL_E2E=1`)
  so the existing `pytest -m e2e` run doesn't silently start downloading
  gigabytes.

**Done when:** a model not yet installed can be pulled from the browser with
visible progress, appears in the model picker the moment it completes and is
immediately selectable for chat, and can be deleted again from the same UI.

---

## Later enhancements (explicitly out of scope for v1)

- Token streaming of the chat reply itself in the UI via SSE (Phase 15
  introduces the same primitive for model-pull progress first).
- OCR + overlay for scanned/non-AcroForm PDFs (harder; form fields first).
- Sandboxed execution for code skills (only if skills ever come from anywhere
  other than the local user).
