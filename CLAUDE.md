# Local AI Assistant

## Project
Local Ollama-based assistant with chat, PDF tools, and RAG. No cloud APIs.
See `plan.md` for current phase and task status. Read it at the start of every session.

## Stack
- Python 3.11+, Streamlit UI
- Ollama at `localhost:11434` — thin API wrapper only, no business logic in `ollama_client.py`
- pdfplumber (read), pypdf (fill AcroForm fields)
- ChromaDB for local vector store, nomic-embed-text for embeddings
- Primary models: qwen2.5 or llama3.1 (both support tool-calling)

## Commands
```bash
streamlit run ui.py
pytest tests/ -v          # fast, mocked, no live model
pytest -m e2e -v          # live model required; skips cleanly if Ollama is down
ruff check . && ruff format .
```

## Key rules
- All Ollama calls go through `ollama_client.py` — nowhere else
- Tool dispatch lives in `agent.py` only — add new tools by adding a function in `tools/` and a case in `_execute_tool()`
- Conversation history source of truth is `memory.py`, not Streamlit session state
- Model name comes from env var `OLLAMA_MODEL`, never hardcoded
- Use `pathlib.Path` for all file I/O

## Gotchas
- pypdf silently succeeds on non-form PDFs without writing — always call `get_fields()` first
- ChromaDB returns distances not scores — lower = more similar, don't invert the sort
- Wrap expensive init (ChromaDB, Ollama health check) in `@st.cache_resource` or Streamlit reruns it every interaction
- Tool call + result pairs in message history must be kept together — never trim one without the other

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
