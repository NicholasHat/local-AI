"""Tests for RAG ingestion, including the Phase 5 definition of done:
an ingested document is findable via the doc_search tool."""

from uuid import uuid4

import chromadb
import pytest

import ingest
import ollama_client
import vectorstore
from tools import doc_search

# --- chunk_text ----------------------------------------------------------


def test_chunk_empty_text():
    assert ingest.chunk_text("   ") == []


def test_chunk_short_text_single_chunk():
    assert ingest.chunk_text("hello world", chunk_size=100, overlap=20) == [
        "hello world"
    ]


def test_chunk_long_text_overlaps_and_covers():
    text = "".join(str(i % 10) for i in range(250))  # 250 chars
    chunks = ingest.chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    # Consecutive chunks overlap by `overlap` chars.
    assert chunks[0][-20:] == chunks[1][:20]
    # Reassembling (accounting for overlap) recovers the whole text.
    rebuilt = chunks[0] + "".join(c[20:] for c in chunks[1:])
    assert rebuilt == text


def test_chunk_rejects_overlap_ge_chunk_size():
    with pytest.raises(ValueError):
        ingest.chunk_text("abc", chunk_size=10, overlap=10)


# --- ingest + retrieve (the DoD) -----------------------------------------


@pytest.fixture
def ephemeral_collection(monkeypatch):
    col = chromadb.EphemeralClient().get_or_create_collection(f"t_{uuid4().hex}")
    monkeypatch.setattr(vectorstore, "get_collection", lambda: col)
    return col


def _keyword_embed(text: str):
    """Deterministic stand-in for a real embedder: python-ish vs cooking-ish."""
    return [1.0, 0.0] if "python" in text.lower() else [0.0, 1.0]


def test_ingest_text_stores_chunks(ephemeral_collection, monkeypatch):
    monkeypatch.setattr(ollama_client, "embed", _keyword_embed)
    n = ingest.ingest_text("some notes about testing", source="notes.txt")
    assert n == 1
    assert ephemeral_collection.count() == 1


def test_ingested_doc_is_findable(ephemeral_collection, monkeypatch):
    monkeypatch.setattr(ollama_client, "embed", _keyword_embed)

    ingest.ingest_text("Python is a programming language.", source="prog.txt")
    ingest.ingest_text("Bake the cake at 180 degrees.", source="recipe.txt")

    result = doc_search.search("tell me about python")
    assert "Python is a programming language." in result
    assert "source=prog.txt" in result


def test_ingest_pdf_findable(ephemeral_collection, monkeypatch, text_pdf):
    monkeypatch.setattr(ollama_client, "embed", lambda t: [1.0, 0.0])
    n = ingest.ingest_pdf(str(text_pdf))
    assert n == 1
    assert "Hello RAG world" in doc_search.search("greeting")


def test_ingest_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        ingest.ingest_pdf("/no/such/file.pdf")


def test_reingest_replaces_not_duplicates(ephemeral_collection, monkeypatch):
    monkeypatch.setattr(ollama_client, "embed", _keyword_embed)
    ingest.ingest_text("first version", source="doc.txt")
    ingest.ingest_text("second version", source="doc.txt")
    assert ephemeral_collection.count() == 1  # same id upserted, not duplicated
