"""Thin ChromaDB wrapper — the local vector store.

Shared by ingestion (Phase 5, `add`) and retrieval (Phase 4, `query`).
Embeddings are always supplied by the caller (produced via ollama_client), so
Chroma is never asked to embed anything itself — no default embedding model is
downloaded.
"""

import chromadb

import config

_COLLECTION = "documents"
_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(config.get_chroma_path()))
    return _client


def get_collection():
    """The single documents collection (created on first use)."""
    return _get_client().get_or_create_collection(_COLLECTION)


def add(ids, embeddings, documents, metadatas) -> None:
    """Upsert chunks. Used by ingestion (Phase 5)."""
    get_collection().upsert(
        ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
    )


def query(embedding, n_results: int = 4) -> list[dict]:
    """Nearest chunks to `embedding`.

    Chroma returns results already sorted by ASCENDING distance (nearest
    first) — lower distance = more similar. We keep that order as-is; do NOT
    invert or treat distance as a similarity score (CLAUDE.md gotcha).
    """
    res = get_collection().query(query_embeddings=[embedding], n_results=n_results)
    documents = res["documents"][0]
    metadatas = res["metadatas"][0]
    distances = res["distances"][0]
    return [
        {"document": doc, "metadata": meta, "distance": dist}
        for doc, meta, dist in zip(documents, metadatas, distances, strict=True)
    ]
