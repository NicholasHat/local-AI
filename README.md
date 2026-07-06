# Private AI Assistant with Tool Use

![status](https://img.shields.io/badge/status-actively%20developing-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![tests](https://img.shields.io/badge/tests-42%20passing-brightgreen)

A locally-run AI assistant (via [Ollama](https://ollama.com)) that can chat,
search your documents (RAG), and read & fill PDF forms — with **no data ever
leaving your machine**. No cloud APIs, no API keys, fully private.

> **Status:** the core (chat, agent loop, RAG, PDF tools, UI) is working and
> tested. I'm actively extending it with a **skills system** and more advanced
> tools — see the [roadmap](#roadmap).

Built from scratch to understand how modern AI agents actually work under the
hood: the tool-calling loop, retrieval-augmented generation, and function
dispatch — the same patterns behind ChatGPT and Claude, running entirely on
local open-source models.

## What it does

- 💬 **Chat** with a local LLM through a clean Streamlit interface
- 🔧 **Uses tools** — the model decides when to call functions, and the agent
  runs them and feeds results back (real function-calling, not prompt hacks)
- 📄 **Reads & fills PDFs** — extracts text and fills interactive form fields
  from plain-English instructions
- 📚 **Chats with your documents** — upload PDFs and ask questions; answers are
  grounded in the content via semantic search (RAG)

## How it works

```
        Streamlit UI
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
        └─────────────────────────────────┘
```

The core is a **tool-calling loop**: the model receives the conversation plus a
set of tool schemas, decides whether to call a tool, and the agent executes it
and returns the result — repeating until the model produces a final answer.
Adding a new capability is just writing a function and registering it.

## Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.11+ |
| Model serving | Ollama (`qwen2.5` for chat, `nomic-embed-text` for embeddings) |
| UI | Streamlit |
| PDF | pdfplumber (read) · pypdf (fill AcroForm fields) |
| Vector store | ChromaDB |
| Tests / lint | pytest · ruff |

## Quickstart

```bash
# 1. Install Ollama and pull the models
ollama serve
ollama pull qwen2.5 && ollama pull nomic-embed-text

# 2. Set up the project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 3. Run
streamlit run ui.py
```

Then open the local URL, drop a PDF into the sidebar, and start asking questions.

## Engineering notes

A few decisions I made deliberately, and why:

- **One choke point for the model.** Every call to Ollama goes through a single
  thin client module. This keeps the agent and tools decoupled from the SDK and
  makes the whole system **unit-testable without a running model** — the test
  suite mocks that one seam.
- **Native function-calling over prompt parsing.** Tool requests are read from
  the model's structured `tool_calls`, not scraped from text — more robust, and
  it shapes a clean conversation-history format.
- **Retrieval and ingestion are separate flows** that share one vector store,
  with a bounded, guard-railed agent loop that can't run away.

## Tests

```bash
pytest        # 42 tests, no live model required
ruff check .
```

The suite covers the agent loop (including the runaway-loop guard), PDF
read/fill (including the trap where pypdf silently "succeeds" on non-form PDFs),
and the full ingest → search retrieval path.

## Roadmap

**Working today**

- [x] Chat with a local LLM via Ollama
- [x] Tool-calling agent loop with a runaway guard
- [x] PDF reading + AcroForm filling
- [x] Document RAG (ingest → embed → semantic search)
- [x] Streamlit web UI with document upload

**Building next**

- [ ] **Skills system** — a registry where each capability registers itself
      (no more editing the agent to add a tool), and a skill can bundle several
      tools plus its own instructions into one self-contained module
- [ ] More advanced tools — web search, code execution, spreadsheet/CSV
      analysis, calendar & email drafting
- [ ] Streaming responses in the UI
- [ ] OCR for scanned (non-interactive) PDFs
- [ ] Persistent, multi-conversation history
