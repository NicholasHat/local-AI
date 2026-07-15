# Private AI Assistant with Tool Use

![status](https://img.shields.io/badge/status-actively%20developing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![tests](https://img.shields.io/badge/tests-123%20passing-brightgreen)

A locally-run AI assistant (via [Ollama](https://ollama.com)) that can chat,
search your documents (RAG), read & fill PDF forms, and grow its own skills —
with **no data ever leaving your machine**. No cloud APIs, no API keys, fully
private.

> **Status:** chat, agent loop, RAG, PDF tools, model management, persisted
> chat history, and a file-based skills system are all working and tested,
> behind a React frontend backed by a FastAPI API. See the
> [roadmap](#roadmap) for what's next.

Built from scratch to understand how modern AI agents actually work under the
hood: the tool-calling loop, retrieval-augmented generation, and function
dispatch — the same patterns behind ChatGPT and Claude, running entirely on
local open-source models.

## What it does

- 💬 **Chat** with a local LLM through a clean React interface
- 🔧 **Uses tools** — the model decides when to call functions, and the agent
  runs them and feeds results back (real function-calling, not prompt hacks)
- 📄 **Reads & fills PDFs** — extracts text and fills interactive form fields
  from plain-English instructions
- 📚 **Chats with your documents** — upload PDFs and ask questions; answers are
  grounded in the content via semantic search (RAG)
- 🧩 **Grows its own skills** — reusable capabilities defined as files
  (`skills/<name>/`), editable from the browser, and the model can even write
  new instruction-based skills for itself on request
- 🔀 **Manages models** — switch between any installed, tool-capable Ollama
  model mid-conversation, or pull new ones straight from the browser with
  live progress (and remove them again) — no terminal required
- 🕘 **Remembers past chats** — every conversation is persisted and listed in
  a short history you can revisit or delete, not lost the moment you start a
  new one
- 🗑️ **Un-attaches documents** — remove an uploaded file and its indexed
  chunks together, from the same sidebar you uploaded it in

## How it works

```
        React UI (web/)
             │  HTTP (/api/*)
        ┌────▼─────┐
        │ FastAPI  │   server.py — routing, active conversation, model choice
        │ server   │
        └────┬─────┘
             │
        ┌────▼─────┐        ┌──────────────┐
        │  Agent   │◄──────►│ Ollama (LLM) │   local model, tool-calling
        │  loop    │        └──────────────┘
        └────┬─────┘
   tool call │ result
        ┌────▼───────────────────────────┐
        │  Tools                          │
        │   • read_pdf / fill_pdf         │  pdfplumber + pypdf
        │   • search_documents (RAG)      │  ChromaDB vector search
        │   • skill__<name>               │  skills/<name>/ — no code change
        └─────────────────────────────────┘
```

The core is a **tool-calling loop**: the model receives the conversation plus a
set of tool schemas (built-in tools + every discovered skill), decides whether
to call one, and the agent executes it and returns the result — repeating
until the model produces a final answer. Adding a capability is either writing
a function and registering it, or dropping a skill file on disk — no restart
required.

## Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.11+ (backend), TypeScript (frontend) |
| Model serving | Ollama (`qwen2.5` for chat, `nomic-embed-text` for embeddings) |
| Backend | FastAPI + uvicorn |
| Frontend | React + Vite + Tailwind (`web/`) |
| PDF | pdfplumber (read) · pypdf (fill AcroForm fields) |
| Vector store | ChromaDB |
| Skills | file-based (`skill.yaml` + `prompt.md` or `run.py`), no sandbox — see [`skills/README.md`](skills/README.md) |
| Conversation history | file-based (`conversations/<id>.json`), same pattern as skills — no database |
| Tests / lint | pytest (unit + live e2e) · ruff · oxlint |

## Quickstart

```bash
# 1. Install Ollama and pull the models
ollama serve
ollama pull qwen2.5 && ollama pull nomic-embed-text

# 2. Set up the backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 3. Build the frontend
cd web && npm install && npm run build && cd ..

# 4. Run (one process, serves the API and the built UI)
uvicorn server:app --port 8000
```

Then open `http://localhost:8000`, drop a PDF into the sidebar, and start
asking questions. For frontend development, run `cd web && npm run dev`
instead of the build step — it proxies API calls to `:8000` and hot-reloads.

## Engineering notes

A few decisions I made deliberately, and why:

- **One choke point for the model.** Every call to Ollama goes through a single
  thin client module. This keeps the agent and tools decoupled from the SDK and
  makes the whole system **unit-testable without a running model** — the test
  suite mocks that one seam. The frontend mirrors this with a single API
  client module (`web/src/api.ts`).
- **Native function-calling over prompt parsing.** Tool requests are read from
  the model's structured `tool_calls`, not scraped from text — more robust, and
  it shapes a clean conversation-history format.
- **Retrieval and ingestion are separate flows** that share one vector store,
  with a bounded, guard-railed agent loop that can't run away.
- **Skills are files, not code changes.** A skill is `skill.yaml` plus either
  `prompt.md` (instructions the model follows) or `run.py` (code it executes,
  no sandbox). The model's own `create_skill` tool can only ever write
  instructions — never code — by construction, not convention: this closes off
  a prompt-injection-to-code-execution path, since content the model reads
  (a document, a search result) can at worst talk it into adding a weird
  instruction to the conversation it already came from, never into writing
  runnable Python. See [`skills/README.md`](skills/README.md) for the full
  reasoning.
- **The frontend never owns assistant state.** Conversation history, the
  active model, and skills all live server-side; the UI re-fetches after
  every mutation instead of keeping a parallel copy.

## Tests

```bash
pytest tests/ -v      # 123 tests, no live model required
pytest -m e2e -v       # live-model tests; skips cleanly if Ollama isn't running
ruff check .
cd web && npm run build && npm run lint
```

The unit suite covers the agent loop (including the runaway-loop guard), PDF
read/fill (including the trap where pypdf silently "succeeds" on non-form
PDFs), the ingest → search retrieval path, the skills registry, the
conversation registry (persistence, title derivation), and the FastAPI
contract — all mocked, no Ollama required. The e2e suite drives the same
tools, the API, model switching, and the skills system (including
self-authoring) against a real running model.

## Roadmap

**Working today**

- [x] Chat with a local LLM via Ollama
- [x] Tool-calling agent loop with a runaway guard
- [x] PDF reading + AcroForm filling
- [x] Document RAG (ingest → embed → semantic search), with the ability to
      un-attach a document (deletes the file and its indexed chunks)
- [x] React web UI with document upload, a tool-activity log, and inline
      model selection
- [x] Runtime model selection across installed, tool-capable Ollama models,
      plus pulling and removing models from the browser (with live progress)
- [x] Persisted, multi-conversation history — switch between past chats or
      start a new one without losing the last
- [x] File-based skills system, including browser-based authoring and
      model self-authoring of instruction skills

**Building next**

- [ ] Streaming responses (token-by-token, via SSE)
- [ ] More advanced tools — web search, code execution, spreadsheet/CSV
      analysis, calendar & email drafting
- [ ] OCR for scanned (non-interactive) PDFs
