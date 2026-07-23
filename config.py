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
