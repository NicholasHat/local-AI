"""Providers — named routing profiles that say which local model plays
which role (plan.md decision 4, Phases 19–26).

A provider is providers/<name>.yaml:

    name: strongest-local
    description: Built from the 2026-09 benchmark run.
    routes:            # role -> installed model tag
      chat: qwen2.5:latest
      coding: qwen2.5:latest
      research: llama3.1:latest
      judge: llama3.1:latest
      fast: llama3.2:1b
      embedding: nomic-embed-text
    options:           # optional per-role Ollama options
      coding: {temperature: 0.1}

The built-in `default` provider has no routes, so every role falls through
to the env defaults — which keeps CLAUDE.md's "never hardcode the model"
rule intact: config.get_model()/get_embed_model() remain the last word.

resolve(role, override) is the ONE resolution order for the whole app:
    explicit override -> session chat override (chat role only)
      -> active provider's route -> env default.

recommend(leaderboard) builds the "strongest local provider" from
measurements (bench.py's leaderboard rows) — a pure function, so this
module never imports bench and bench can import this one for its judge.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import config
import ollama_client
import settings

PROVIDERS_DIR = Path("providers")
ROLES = ("chat", "coding", "research", "judge", "fast", "embedding")
AGENTIC_ROLES = ("chat", "coding", "research")  # need tool-calling models
DEFAULT_NAME = "default"

_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProviderError(Exception):
    """Invalid provider name/definition, or no such provider."""


@dataclass
class Provider:
    name: str
    description: str = ""
    routes: dict[str, str] = field(default_factory=dict)
    options: dict[str, dict] = field(default_factory=dict)
    builtin: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "routes": dict(self.routes),
            "options": {k: dict(v) for k, v in self.options.items()},
            "builtin": self.builtin,
        }


_DEFAULT = Provider(
    name=DEFAULT_NAME,
    description=(
        "Environment defaults: OLLAMA_MODEL for every model role, "
        "OLLAMA_EMBED_MODEL for embeddings."
    ),
    builtin=True,
)


def _validate_name(name: str) -> None:
    if name == DEFAULT_NAME:
        raise ProviderError(f"{DEFAULT_NAME!r} is built in and can't be written.")
    if not _NAME_PATTERN.match(name or ""):
        raise ProviderError(
            f"Invalid provider name {name!r}: lowercase letters, digits, hyphens."
        )


def _validate_routes(routes: dict, options: dict) -> None:
    bad = set(routes) - set(ROLES)
    if bad:
        raise ProviderError(f"Unknown role(s) {sorted(bad)}; roles are {ROLES}.")
    bad = set(options) - set(ROLES)
    if bad:
        raise ProviderError(f"Options for unknown role(s) {sorted(bad)}.")
    for role, model in routes.items():
        if not isinstance(model, str) or not model.strip():
            raise ProviderError(f"Route for {role!r} must be a model name.")
    for role, opts in options.items():
        if not isinstance(opts, dict):
            raise ProviderError(f"Options for {role!r} must be a mapping.")


def _path(name: str) -> Path:
    return PROVIDERS_DIR / f"{name}.yaml"


def _load_file(path: Path) -> Provider:
    data = yaml.safe_load(path.read_text()) or {}
    routes = {k: str(v) for k, v in (data.get("routes") or {}).items()}
    options = data.get("options") or {}
    _validate_routes(routes, options)
    return Provider(
        name=path.stem,
        description=str(data.get("description") or ""),
        routes=routes,
        options=options,
    )


def discover() -> list[Provider]:
    """The built-in default first, then every valid providers/*.yaml.
    Malformed files are skipped, never fatal (same posture as skills.py)."""
    found = [_DEFAULT]
    if PROVIDERS_DIR.exists():
        for path in sorted(PROVIDERS_DIR.glob("*.yaml")):
            if not _NAME_PATTERN.match(path.stem):
                continue
            try:
                found.append(_load_file(path))
            except (ProviderError, yaml.YAMLError, AttributeError):
                continue
    return found


def get(name: str) -> Provider:
    if name == DEFAULT_NAME:
        return _DEFAULT
    if not _NAME_PATTERN.match(name or "") or not _path(name).exists():
        raise ProviderError(f"No such provider: {name!r}")
    try:
        return _load_file(_path(name))
    except (yaml.YAMLError, AttributeError) as exc:
        raise ProviderError(f"Provider {name!r} is malformed: {exc}") from exc


def save(
    name: str,
    description: str,
    routes: dict[str, str],
    options: dict[str, dict] | None = None,
) -> Provider:
    _validate_name(name)
    options = options or {}
    _validate_routes(routes, options)
    PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)
    provider = Provider(
        name=name, description=description, routes=routes, options=options
    )
    _path(name).write_text(
        yaml.safe_dump(
            {"description": description, "routes": routes, "options": options},
            sort_keys=False,
        )
    )
    return provider


def delete(name: str) -> None:
    _validate_name(name)
    if not _path(name).exists():
        raise ProviderError(f"No such provider: {name!r}")
    _path(name).unlink()
    if settings.get("active_provider") == name:
        settings.update(active_provider=DEFAULT_NAME)


def active() -> Provider:
    """The active provider, falling back to default if the setting points
    at a provider that no longer exists."""
    try:
        return get(settings.get("active_provider") or DEFAULT_NAME)
    except ProviderError:
        return _DEFAULT


def activate(name: str) -> Provider:
    """Make `name` active. Also clears the session chat-model override so
    the provider's chat route actually takes effect."""
    provider = get(name)
    settings.update(active_provider=name, chat_model=None)
    return provider


def resolve(role: str, override: str | None = None) -> str | None:
    """The one model-resolution order for the whole app (module docstring).
    Returns None only when nothing at all is configured for the role."""
    if role not in ROLES:
        raise ProviderError(f"Unknown role {role!r}; roles are {ROLES}.")
    if override:
        return override
    if role == "chat":
        session_override = settings.get("chat_model")
        if session_override:
            return session_override
    routed = active().routes.get(role)
    if routed:
        return routed
    if role == "embedding":
        return config.get_embed_model()
    try:
        return config.get_model()
    except RuntimeError:
        return None


def tool_capable_models() -> set[str] | None:
    """Installed models that can call tools, or None when Ollama can't be
    asked (callers then assume every model is capable and let Ollama's own
    error surface). Ollama rejects tool schemas outright for models without
    tool support, so anything that advertises tools must check first."""
    try:
        return {
            m["name"]
            for m in ollama_client.list_models()
            if "tools" in m["capabilities"]
        }
    except Exception:
        return None


def supports_tools(model: str, capable: set[str] | None = None) -> bool:
    """Whether `model` can call tools. An untagged name matches its ":latest"
    tag, as Ollama itself resolves it. Unknown (Ollama unreachable) -> True."""
    capable = tool_capable_models() if capable is None else capable
    if capable is None:
        return True
    return model in capable or f"{model}:latest" in capable


def resolve_options(role: str) -> dict | None:
    """Per-role Ollama options from the active provider, if any."""
    return active().options.get(role) or None


# --- Recommendation ----------------------------------------------------------

# Which leaderboard categories feed each role. Scores are 0..1 per category
# (bench.py); a role's fitness is the mean of its listed categories.
_ROLE_CATEGORIES = {
    "chat": ("instruction", "reasoning", "knowledge", "tools"),
    "coding": ("coding", "tools", "json"),
    "research": ("knowledge", "reasoning", "tools", "instruction"),
    "judge": ("reasoning", "instruction"),
}


def _fitness(row: dict, categories: tuple[str, ...]) -> float | None:
    scores = [row["categories"][c] for c in categories if c in row["categories"]]
    return sum(scores) / len(scores) if scores else None


def recommend(leaderboard: list[dict], installed: set[str] | None = None) -> Provider:
    """Compose the strongest provider from measured results.

    `leaderboard` rows are bench.py's shape: {"model", "tool_capable",
    "overall", "categories": {name: 0..1}, "tokens_per_sec"}. `installed`
    (model names) restricts choices to what's actually on disk — a vaulted
    or deleted model can't be routed to. Agentic roles require tool-capable
    models. `fast` is the quickest model that still scores at least half of
    the best overall score. Embedding stays on the env default (the suite
    doesn't measure embeddings).
    """
    rows = [r for r in leaderboard if installed is None or r["model"] in installed]
    if not rows:
        raise ProviderError("No benchmark results for any installed model yet.")

    routes: dict[str, str] = {}
    for role, categories in _ROLE_CATEGORIES.items():
        candidates = [r for r in rows if r["tool_capable"] or role not in AGENTIC_ROLES]
        scored = [
            (f, r) for r in candidates if (f := _fitness(r, categories)) is not None
        ]
        if scored:
            scored.sort(
                key=lambda fr: (fr[0], fr[1]["tokens_per_sec"] or 0), reverse=True
            )
            routes[role] = scored[0][1]["model"]

    best_overall = max(r["overall"] for r in rows)
    quick = [
        r for r in rows if r["overall"] >= best_overall / 2 and r["tokens_per_sec"]
    ]
    if quick:
        routes["fast"] = max(quick, key=lambda r: r["tokens_per_sec"])["model"]

    if not routes:
        raise ProviderError("No installed model scored on the benchmark suite.")
    return Provider(
        name="recommended",
        description="Best measured model per role from the benchmark leaderboard.",
        routes=routes,
    )
