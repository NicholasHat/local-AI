"""Streamlit UI — wires the whole assistant together.

Design notes:
- The Conversation (memory.py) is the SOURCE OF TRUTH for history. It lives in
  st.session_state only so it survives Streamlit's per-interaction reruns; the
  chat transcript is always rendered FROM conv.messages, never from a second
  parallel list.
- Expensive init (warming the Chroma client + probing Ollama) is wrapped in
  @st.cache_resource so it runs once, not on every rerun.
"""

import streamlit as st

import agent
import config
import ingest
import ollama_client
from memory import Conversation
from vectorstore import get_collection

SYSTEM_PROMPT = (
    "You are a helpful local assistant with tools for PDFs and documents. "
    "Documents the user uploads in the sidebar are already available to you: "
    "read a whole uploaded document with read_uploaded_document(filename), and "
    "answer specific questions across uploaded documents with search_documents. "
    "Use read_pdf / list_pdf_fields / fill_pdf only for files at a filesystem "
    "path the user explicitly gives you. Never ask the user for a file path to "
    "a document they uploaded in the sidebar. Prefer tools over guessing, and "
    "cite sources when answering from documents."
)


@st.cache_resource
def init_resources() -> dict:
    """Run-once startup: warm the vector store and probe Ollama."""
    get_collection()  # creates/opens the persistent Chroma store once
    return {"healthy": ollama_client.health_check()}


def get_conversation() -> Conversation:
    """The per-session Conversation, created once and kept in session_state."""
    if "conversation" not in st.session_state:
        st.session_state.conversation = Conversation(system_prompt=SYSTEM_PROMPT)
    return st.session_state.conversation


def _current_model() -> str | None:
    try:
        return config.get_model()
    except RuntimeError:
        return None


def _handle_uploads(files, conv: Conversation) -> None:
    """Ingest newly uploaded PDFs once each (dedup by name+size across reruns),
    and tell the model each document now exists so it can actually use it."""
    ingested = st.session_state.setdefault("ingested_files", set())
    upload_dir = config.get_upload_dir()
    upload_dir.mkdir(exist_ok=True)

    for f in files:
        key = (f.name, f.size)
        if key in ingested:
            continue
        dest = upload_dir / f.name
        dest.write_bytes(f.getbuffer())
        with st.spinner(f"Indexing {f.name}…"):
            try:
                n = ingest.ingest_pdf(str(dest))
                st.success(f"Indexed {f.name} ({n} chunk{'s' if n != 1 else ''}).")
                conv.add_system_note(
                    f"The user uploaded a document named '{f.name}'. Read its full "
                    f"text with read_uploaded_document(filename='{f.name}'), or "
                    "answer specific questions about it with search_documents. Do "
                    "not ask the user for a file path."
                )
            except Exception as exc:  # noqa: BLE001 - surface any ingest failure
                st.error(f"Failed to index {f.name}: {exc}")
        ingested.add(key)


def _render_history(conv: Conversation) -> None:
    """Render the transcript from memory (the source of truth)."""
    for msg in conv.messages:
        role = msg["role"]
        if role == "user":
            st.chat_message("user").write(msg["content"])
        elif role == "assistant" and msg.get("content"):
            st.chat_message("assistant").write(msg["content"])
        elif role == "tool":
            st.caption(f"🔧 used tool: {msg.get('tool_name', 'unknown')}")


def main() -> None:
    st.set_page_config(page_title="Local AI Assistant", page_icon="🤖")
    st.title("🤖 Local AI Assistant")

    resources = init_resources()
    conv = get_conversation()
    model = _current_model()

    with st.sidebar:
        st.subheader("Status")
        if not resources["healthy"]:
            st.error("Ollama not reachable. Start it with `ollama serve`.")
        elif model is None:
            st.warning("Set OLLAMA_MODEL in your .env file.")
        else:
            st.success(f"Connected · model: {model}")
        if st.button("Recheck connection"):
            init_resources.clear()
            st.rerun()

        st.divider()
        st.subheader("Documents (RAG)")
        uploads = st.file_uploader(
            "Upload PDFs to chat with", type=["pdf"], accept_multiple_files=True
        )
        if uploads:
            _handle_uploads(uploads, conv)

        st.divider()
        if st.button("Clear conversation"):
            del st.session_state["conversation"]
            st.rerun()

    _render_history(conv)

    if prompt := st.chat_input("Ask a question, or ask about your documents…"):
        if not resources["healthy"] or model is None:
            st.error("Cannot chat until Ollama is reachable and OLLAMA_MODEL is set.")
            return

        st.chat_message("user").write(prompt)
        with st.chat_message("assistant"), st.spinner("Thinking…"):
            try:
                reply = agent.run(prompt, conv)
            except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
                reply = f"Something went wrong: {exc}"
            st.write(reply)


if __name__ == "__main__":
    main()
