"""Central config. Loads .env and exposes settings via functions.

Accessors are lazy (functions, not import-time constants) so importing this
module never crashes when OLLAMA_MODEL is unset — tests import freely.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_model() -> str:
    """Chat model name. No hardcoded default — enforces the OLLAMA_MODEL rule."""
    model = os.getenv("OLLAMA_MODEL")
    if not model:
        raise RuntimeError(
            "OLLAMA_MODEL is not set. Copy .env.example to .env and set it."
        )
    return model


def get_embed_model() -> str:
    """Embedding model for RAG. CLAUDE.md pins nomic-embed-text as the default."""
    return os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def get_host() -> str:
    """Ollama API base URL."""
    return os.getenv("OLLAMA_HOST", "http://localhost:11434")


def get_chroma_path() -> Path:
    """On-disk location for the ChromaDB store (gitignored)."""
    return Path(os.getenv("CHROMA_PATH", "chroma"))


def get_upload_dir() -> Path:
    """Directory where files uploaded via the UI are saved (gitignored)."""
    return Path(os.getenv("UPLOAD_DIR", "uploads"))


def get_coding_workspace_root() -> Path:
    """Allowlisted root for the coding agent's target repos (Phase 16). A
    requested repo_path must resolve to this directory or somewhere beneath
    it — the guard that keeps a fallible model-driven run from ever being
    pointed at '/' or some other directory the user never opted into.
    Defaults to ~/coding-workspace; override via CODING_WORKSPACE_ROOT."""
    root = os.getenv("CODING_WORKSPACE_ROOT", str(Path.home() / "coding-workspace"))
    return Path(root).resolve()


def get_coding_test_command() -> str:
    """The command run_tests() runs inside the worktree. The model chooses
    *when* to test, never *what* to run — this stays a fixed, configured
    command, not an arbitrary shell tool."""
    return os.getenv("CODING_TEST_COMMAND", "pytest -q")


def web_tools_enabled() -> bool:
    """Whether the chat agent may advertise web_search / fetch_url
    (tools/web.py). The network is only ever used to read public pages —
    never to run inference — and can be switched off entirely with
    ENABLE_WEB_TOOLS=false for a fully offline posture."""
    return os.getenv("ENABLE_WEB_TOOLS", "true").lower() not in {"0", "false", "no"}


def get_searxng_url() -> str | None:
    """Optional self-hosted SearXNG base URL. When set, web_search queries
    it (JSON API) instead of scraping DuckDuckGo's HTML endpoint."""
    return os.getenv("SEARXNG_URL") or None


def get_vault_dir() -> Path:
    """Where vault.py archives model manifests + blobs (an external drive, a
    NAS...). Defaults to ~/model-vault; override via MODEL_VAULT_DIR."""
    return Path(os.getenv("MODEL_VAULT_DIR", str(Path.home() / "model-vault")))


def get_ollama_models_dir() -> Path:
    """Ollama's on-disk model store (manifests/ + blobs/). Honors the same
    OLLAMA_MODELS variable the Ollama server itself reads."""
    return Path(os.getenv("OLLAMA_MODELS", str(Path.home() / ".ollama" / "models")))
