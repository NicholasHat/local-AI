"""Search tool: the retrieval half of RAG.

Embeds the query via ollama_client (all Ollama traffic goes through there),
then asks the vector store for the nearest chunks. Ingestion is Phase 5.
"""

import ollama_client
import vectorstore


def search(query: str, n_results: int = 4, sources: list[str] | None = None) -> str:
    """Return the most relevant document chunks as a readable string.
    `sources` (filenames) restricts the search — None means every document."""
    embedding = ollama_client.embed(query)
    hits = vectorstore.query(embedding, n_results=n_results, sources=sources)

    if not hits:
        return "No matching documents (nothing indexed yet, or no results)."

    blocks = []
    for i, hit in enumerate(hits, 1):
        source = hit["metadata"].get("source", "unknown")
        blocks.append(
            f"[{i}] source={source} distance={hit['distance']:.3f}\n{hit['document']}"
        )
    return "\n\n".join(blocks)
