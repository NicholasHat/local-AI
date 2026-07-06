"""Thin wrapper — the single choke point for ALL Ollama traffic.

Rule (CLAUDE.md): every call to Ollama, including embeddings, goes through
here. No business logic in this module — just request/response passthrough.

Implemented in Phase 2.
"""


def chat(messages, tools=None, model=None):
    """Call /api/chat. Returns the raw response message (incl. tool_calls)."""
    raise NotImplementedError("Phase 2")


def embed(text, model=None):
    """Call /api/embed with the embedding model. Returns a vector."""
    raise NotImplementedError("Phase 2")


def health_check() -> bool:
    """Return True if Ollama is reachable. Used by the UI at startup."""
    raise NotImplementedError("Phase 2")
