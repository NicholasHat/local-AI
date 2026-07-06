"""Streamlit UI. Wires everything together (Phase 6).

Chat backed by memory.py (not st.session_state as source of truth). File
upload triggers RAG ingestion. Expensive init (ChromaDB client, Ollama
health check) must be wrapped in @st.cache_resource.
"""


def main():
    raise NotImplementedError("Phase 6")


if __name__ == "__main__":
    main()
