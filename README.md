# Private AI Assistant with Tool Use

![status](https://img.shields.io/badge/status-actively%20developing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![tests](https://img.shields.io/badge/tests-345%20passing-brightgreen)

A locally-run AI assistant (via [Ollama](https://ollama.com)) that can chat,
search your documents (RAG), read & fill PDF forms, grow its own skills,
run multi-model agentic workflows, benchmark and compare the models you
hold, archive their weights, and edit code in your local repos under human
approval — with **no inference ever leaving your machine**. No cloud AI
APIs, no API keys. The network is used only to discover and fetch open
models and read public pages, and every page works offline.

> **Status:** chat, agent loop, RAG, PDF tools, model management, persisted
> chat history, a file-based skills system, a sandboxed coding agent, and
> the model-sovereignty layer (catalog + vault, benchmarks + arena,
> providers, workflows, shared spaces, projects) are all working and tested,
> behind a React frontend backed by a FastAPI API. See the
> [roadmap](#roadmap) for what's next.

**Why the sovereignty layer:** if frontier models go closed or open weights
become subscription-gated, this app should already hold every model worth
having and be able to use them well. The **vault** keeps the weights safe
in a plain directory; the **catalog** and update check keep the local set
current; **benchmarks** say which local model is strongest at what; a
**provider** routes each role (chat, coding, research, judge, fast) to the
best measured model; **workflows** compose those models into research,
council, and planning pipelines; and **spaces** let them talk to each
other — and to you — on a shared board.

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
- 🛠️ **Writes code in your own repos** — describe a change on the Coding
  page, and a second, sandboxed agent plans it, edits files, and runs your
  tests inside a throwaway git worktree; you watch every step stream in live
  and review the diff before **Approve** lands it on your working branch (or
  **Discard** throws it away, untouched)
- 🧠 **Holds the models** — a dated catalog of open-weight families (with
  licenses, sizes, capabilities), the Hugging Face trending GGUF feed
  (pullable as `hf.co/<org>/<repo>`), an update check against Ollama's
  registry, a full details explorer for everything installed, custom builds
  (base + system prompt + parameters → a new local model), and a **vault**
  that archives a model's manifest + blobs to any directory and restores
  them without a registry
- ⚖️ **Compares models** — a deterministic local benchmark suite (reasoning,
  coding, instruction, tools, JSON, knowledge) with a leaderboard including
  tokens/sec, and an **arena** that runs one prompt across several models
  side by side with an optional judge model scoring each answer
- 🧭 **Routes by role** — providers map chat / coding / research / judge /
  fast / embedding roles to installed models; one click composes the
  strongest provider from the leaderboard
- 🔁 **Runs agentic workflows** — YAML-defined multi-step, multi-model
  pipelines (built-in: `research`, `council`, `project-brief`), with fan-out
  over models, per-step tool allowlists, live step streaming, and a shared
  space per run
- 🗣️ **Lets models talk** — shared spaces are persisted boards any agent can
  read and post to (`read_space` / `post_to_space`); you can watch live or
  post into the conversation yourself
- 📁 **Organizes work into projects** — goal, notes, attached documents,
  linked chats and runs; an active project scopes document search and
  gives the model its goal and notes as context
- 🌐 **Researches the web** — `web_search` (SearXNG if configured, else
  DuckDuckGo, else Wikipedia) and `fetch_url`; switch off with one env flag

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

The **coding agent is a second, separate loop**, reachable only from the
Coding page — never a chat tool:

```
   Coding page (web/)
        │  HTTP (/api/coding/*), steps stream live over SSE
   ┌────▼─────┐        ┌──────────────┐
   │  Coding  │◄──────►│ Ollama (LLM) │   same local model, tool-calling
   │  agent   │        └──────────────┘
   │  loop    │  coding_agent.py — its own _execute_coding_tool() dispatch
   └────┬─────┘
tool call│ result — every step appended to runs/<id>.json
   ┌────▼─────────────────────────────────────┐
   │  git worktree (scratch branch off HEAD)   │
   │   • list_files / read_file / write_file   │  confined to the
   │   • run_tests (configured test command)   │  worktree root
   └────────────────┬───────────────────────────┘
                     │ diff
              ┌──────▼───────┐
              │ human review │  Approve → merges to the working branch
              │ (Coding page)│  Discard → worktree removed, repo untouched
              └──────────────┘
```

The worktree is the sandbox, the diff, and the undo — all three. The agent
only edits files and runs tests inside that disposable checkout; nothing
touches the real branch until a human reads the diff and clicks **Approve**.
**Discard** removes the worktree, and the real repo was never touched.

**Workflows reuse the chat loop, never the coding loop.** A workflow step is
a fresh conversation run through `agent.run()` with an explicit tool
allowlist, so the most a workflow can ever do is what a chat turn can do
(documents, search, web, skills, spaces). Steps form a DAG; independent
steps run in parallel; `each:` fans a step out over a list of models. Every
run gets a shared space, and each step's output is posted there under the
step's identity — that space *is* the inter-model transcript:

```
   Workflows page            workflows/<name>.yaml
        │ start                  (inputs, steps, tools, depends_on, each)
   ┌────▼──────────┐   step = Conversation + agent.run(tools=[allowlist])
   │ workflows.py  │──────────────┐
   │ DAG runner    │  fan-out     │   spaces/<id>.json  ◄── read_space /
   └────┬──────────┘  in threads  │   (posts by "step @ model")  post_to_space
        │ events → jobs/workflow/<id>.json → SSE → live step cards
```

**Model choice is one resolution order everywhere** —
`providers.resolve(role)`: explicit choice → composer override → active
provider's route → env default. Benchmarks feed `providers.recommend()`,
so "the strongest local provider" is computed from measurements, not
guessed.

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
| Coding agent | separate loop (`coding_agent.py`), isolated in a `git worktree` per run — see [Engineering notes](#engineering-notes) |
| Workflows / spaces / projects / providers | file-based (`workflows/*.yaml`, `spaces/`, `projects/`, `providers/*.yaml`), runs in a generic job store (`jobs/<kind>/`) |
| Model catalog / vault | `catalog.yaml` seed + Hugging Face trending feed + registry manifest check; `vault.py` copies Ollama manifests + blobs to `MODEL_VAULT_DIR` |
| Benchmarks | `benchmarks/suite.yaml`, deterministic checkers, results in `bench_results/` |
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
- **Isolation replaces prohibition for the coding agent.** Every other tool in
  this app is in-process with no sandbox because the chat model can never run
  code it wrote (`create_skill` structurally can't emit a `run.py`). The
  coding agent deliberately crosses that line, so instead: it is a *separate*
  loop with its own smaller tool set, started only by an explicit human
  action (never a chat tool), and it can only edit files and run tests
  **inside a throwaway `git worktree` on a scratch branch**. Approving copies
  that diff onto the real branch; discarding removes the worktree — the real
  branch is never touched either way. See `plan.md`'s Phase 16–18 decisions
  for the full reasoning.

## Tests

```bash
pytest tests/ -v      # 345 tests, no live model required
pytest -m e2e -v       # live-model tests; skips cleanly if Ollama isn't running
ruff check .
cd web && npm run build && npm run lint
```

The unit suite covers the agent loop (including the runaway-loop guard), PDF
read/fill (including the trap where pypdf silently "succeeds" on non-form
PDFs), the ingest → search retrieval path, the skills registry, the
conversation registry (persistence, title derivation), the coding-agent loop
and its worktree lifecycle (path-confinement rejection, apply/discard against
a real throwaway git repo), the run log store, and the FastAPI contract — all
mocked or against real-but-disposable git repos, no Ollama required. The e2e
suite drives the same tools, the API, model switching, and the skills system
(including self-authoring) against a real running model; a live e2e run of
the coding agent itself is not yet in that suite (see [roadmap](#roadmap)).

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
- [x] Sandboxed coding agent — a dedicated Coding page starts a second,
      confined agent loop that edits and tests a real local repo inside a
      throwaway `git worktree`, with a live streaming step log, a diff
      viewer, and human Approve/Discard before anything reaches a real
      branch
- [x] Model sovereignty layer — catalog + trending + update check + vault,
      benchmarks + arena, providers, workflows, shared spaces, projects,
      web search/fetch tools (Phases 19–26)

**Building next**

- [ ] Multi-agent coding review — writer/tester/security-reviewer roles
      layered on the same coding-agent loop and worktree, one shared run log
- [ ] Live e2e coverage for the coding agent against a real model and a
      fixture repo
- [ ] Streaming responses (token-by-token, via SSE) for chat replies
- [ ] More chat tools — spreadsheet/CSV analysis, calendar & email drafting
- [ ] Scheduled "stay current" runs (periodic trending/update checks and a
      digest posted to a space)
- [ ] OCR for scanned (non-interactive) PDFs
