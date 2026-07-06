"""Thin wrapper — the single choke point for ALL Ollama traffic.

Rule (CLAUDE.md): every call to Ollama, including embeddings, goes through
here. No business logic in this module — just request/response passthrough,
normalized to plain Python types so the rest of the app never imports the
ollama SDK directly (which keeps agent/tools mockable — see tests).

Schema reference: docs/ollama-tool-calling.md.
"""

from ollama import Client

import config

_client: Client | None = None


def _get_client() -> Client:
    """Lazily build one Client. Lazy so importing this module never needs a
    host to be reachable (tests import freely)."""
    global _client
    if _client is None:
        _client = Client(host=config.get_host())
    return _client


def _as_dict(obj) -> dict:
    """Normalize an ollama pydantic response object to a plain dict."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def chat(messages, tools=None, model=None) -> dict:
    """Call /api/chat (non-streaming).

    Returns the assistant message as a plain dict: {"role", "content", and
    "tool_calls" when the model requested tools}. See docs/ollama-tool-calling.md.
    """
    model = model or config.get_model()
    response = _get_client().chat(
        model=model, messages=messages, tools=tools, stream=False
    )
    return _as_dict(response.message)


def embed(text: str, model=None) -> list[float]:
    """Call /api/embed with the embedding model. Returns a single vector."""
    model = model or config.get_embed_model()
    response = _get_client().embed(model=model, input=text)
    return response.embeddings[0]


def health_check() -> bool:
    """Return True if Ollama is reachable. Used by the UI at startup."""
    try:
        _get_client().list()
        return True
    except Exception:
        return False
