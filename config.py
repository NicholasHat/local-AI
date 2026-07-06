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
