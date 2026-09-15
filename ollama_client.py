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


_STAT_KEYS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
    "done_reason",
)


def chat_stats(messages, tools=None, model=None, options=None) -> dict:
    """Call /api/chat (non-streaming) and return BOTH the assistant message
    and the response's timing/token metrics:

        {"message": {"role", "content", "tool_calls"?},
         "stats": {"total_duration", "load_duration", "prompt_eval_count",
                   "prompt_eval_duration", "eval_count", "eval_duration",
                   "done_reason"}}

    Durations are nanoseconds, exactly as Ollama reports them (verified
    live 2026-09-15). `options` is Ollama's per-request options mapping
    (temperature, num_ctx, ...), passed through untouched.
    """
    model = model or config.get_model()
    response = _get_client().chat(
        model=model, messages=messages, tools=tools, stream=False, options=options
    )
    stats = {key: getattr(response, key, None) for key in _STAT_KEYS}
    return {"message": _as_dict(response.message), "stats": stats}


def chat(messages, tools=None, model=None, options=None) -> dict:
    """Call /api/chat (non-streaming); return just the assistant message as a
    plain dict: {"role", "content", and "tool_calls" when the model requested
    tools}. See docs/ollama-tool-calling.md. Use chat_stats() when the
    timing/token metrics matter (benchmarks, arena)."""
    return chat_stats(messages, tools=tools, model=model, options=options)["message"]


def embed(text: str, model=None) -> list[float]:
    """Call /api/embed with the embedding model. Returns a single vector."""
    model = model or config.get_embed_model()
    response = _get_client().embed(model=model, input=text)
    return response.embeddings[0]


def list_models() -> list[dict]:
    """List installed models with name, size, digest, and capabilities
    (e.g. "tools").

    The SDK's `list()` response doesn't surface `capabilities` — only a
    per-model `show()` call does (verified against a live server) — so we
    fetch it once per model. Small N (a handful of local models), and not on
    the hot path, so the extra round trips are a non-issue. `digest` is the
    manifest digest Ollama reports for the installed tag — what an update
    check compares against the registry (catalog.py).
    """
    client = _get_client()
    models = []
    for m in client.list().models:
        info = client.show(m.model)
        models.append(
            {
                "name": m.model,
                "size": m.size,
                "digest": getattr(m, "digest", None),
                "capabilities": list(info.capabilities or []),
            }
        )
    return models


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def show_model(name: str) -> dict:
    """Full details for one installed model, normalized from `show()`:
    family/parameter size/quantization (details), context length and
    parameter count (modelinfo, keyed by architecture — verified live:
    e.g. "qwen2.context_length"), the license's first line, capabilities,
    template/system/parameters. Shape-normalization only, no business logic.
    """
    info = _as_dict(_get_client().show(name))
    details = info.get("details") or {}
    modelinfo = info.get("modelinfo") or {}
    arch = modelinfo.get("general.architecture") or details.get("family") or ""
    return {
        "name": name,
        "family": details.get("family") or "",
        "families": list(details.get("families") or []),
        "parameter_size": details.get("parameter_size") or "",
        "quantization_level": details.get("quantization_level") or "",
        "format": details.get("format") or "",
        "architecture": arch,
        "context_length": modelinfo.get(f"{arch}.context_length"),
        "parameter_count": modelinfo.get("general.parameter_count"),
        "license": _first_line(info.get("license")),
        "license_link": modelinfo.get("general.license.link") or "",
        "base_model": modelinfo.get("general.base_model.0.name") or "",
        "capabilities": list(info.get("capabilities") or []),
        "modified_at": _iso(info.get("modified_at")),
        "template": info.get("template") or "",
        "system": info.get("system") or "",
        "parameters": info.get("parameters") or "",
    }


def create_model(
    name: str,
    from_model: str,
    system: str | None = None,
    parameters: dict | None = None,
    template: str | None = None,
) -> dict:
    """`ollama create` from an installed base: a new local tag with its own
    system prompt / parameters (the Modelfile fields the SDK 0.6 `create()`
    accepts directly — verified from its signature). Passthrough only."""
    response = _get_client().create(
        model=name,
        from_=from_model,
        system=system,
        parameters=parameters,
        template=template,
        stream=False,
    )
    return _as_dict(response)


def running_models() -> list[dict]:
    """Models currently loaded in memory (`ollama ps`)."""
    return [
        {
            "name": m.model,
            "size": getattr(m, "size", None),
            "size_vram": getattr(m, "size_vram", None),
            "expires_at": _iso(getattr(m, "expires_at", None)),
        }
        for m in _get_client().ps().models
    ]


def pull_model(name: str):
    """Stream progress for `ollama pull <name>`. Yields plain dicts (typically
    `status`, and `completed`/`total` once a layer starts downloading) —
    passthrough only, no retry/business logic, same as the rest of this
    module."""
    for update in _get_client().pull(model=name, stream=True):
        yield _as_dict(update)


def delete_model(name: str) -> None:
    """Remove a locally pulled model."""
    _get_client().delete(model=name)


def health_check() -> bool:
    """Return True if Ollama is reachable. Used by the UI at startup."""
    try:
        _get_client().list()
        return True
    except Exception:
        return False
