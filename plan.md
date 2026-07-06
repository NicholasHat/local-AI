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

---

## Later enhancements (explicitly out of scope for v1)

- Token streaming in the UI (layered onto the working non-streaming loop).
- OCR + overlay for scanned/non-AcroForm PDFs (harder; form fields first).
- Multiple concurrent conversations / persisted history across sessions.
