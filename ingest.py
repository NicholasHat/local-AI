"""RAG ingestion — the *ingest* flow (distinct from retrieval in doc_search).

Pipeline: read text -> chunk -> embed each chunk (via ollama_client) -> store
in the vector store with metadata. Triggered by file upload in the UI (Phase 6).

Ingestion and retrieval share the Chroma collection but are separate code paths.
Chunk IDs are deterministic (`source::index`) and stored via upsert, so
re-ingesting the same file replaces its chunks instead of duplicating them.
"""

from pathlib import Path

import ollama_client
import vectorstore
from tools import pdf_reader


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into overlapping character windows.

    Overlap keeps context from straddling a boundary so retrieval doesn't miss
    facts split across two chunks.
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


def ingest_text(
    text: str, source: str, chunk_size: int = 1000, overlap: int = 150
) -> int:
    """Chunk, embed, and store `text` under `source`. Returns chunk count."""
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        return 0

    ids = [f"{source}::{i}" for i in range(len(chunks))]
    embeddings = [ollama_client.embed(chunk) for chunk in chunks]
    metadatas = [{"source": source, "chunk": i} for i in range(len(chunks))]

    vectorstore.add(
        ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas
    )
    return len(chunks)


def ingest_pdf(path: str) -> int:
    """Extract a PDF's text and ingest it under its filename. Returns chunk count."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    text = pdf_reader.read_text(p)
    return ingest_text(text, source=p.name)
