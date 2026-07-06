# Local AI Assistant

Local Ollama-based assistant with chat, PDF tools, and RAG. No cloud APIs.

## Stack
- Python 3.11+, Streamlit UI
- Ollama at `localhost:11434` — thin API wrapper only, no business logic in `ollama_client.py`
- pdfplumber (read), pypdf (fill AcroForm fields)
- ChromaDB for local vector store, nomic-embed-text for embeddings
- Primary models: qwen2.5 or llama3.1 (both support tool-calling)

## Commands
```bash
streamlit run ui.py
pytest tests/ -v
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
### 1. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it
