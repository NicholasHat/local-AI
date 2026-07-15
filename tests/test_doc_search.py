"""Tests for the vector store and the doc_search tool.

Uses an in-memory (ephemeral) Chroma collection and a mocked embed function —
no persistent store, no live Ollama."""

from uuid import uuid4

import chromadb
import pytest

import ollama_client
import vectorstore
from tools import doc_search


@pytest.fixture
def ephemeral_collection(monkeypatch):
    # EphemeralClient shares one in-memory instance across calls, so use a
    # unique collection name per test to avoid cross-test bleed.
    col = chromadb.EphemeralClient().get_or_create_collection(f"t_{uuid4().hex}")
    monkeypatch.setattr(vectorstore, "get_collection", lambda: col)
    return col


def test_query_keeps_ascending_distance_order(ephemeral_collection):
    ephemeral_collection.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["apple", "banana"],
        metadatas=[{"source": "x"}, {"source": "y"}],
    )
    hits = vectorstore.query([0.9, 0.1], n_results=2)
    assert [h["document"] for h in hits] == ["apple", "banana"]  # nearest first
    assert hits[0]["distance"] < hits[1]["distance"]


def test_doc_search_formats_hits(ephemeral_collection, monkeypatch):
    ephemeral_collection.add(
        ids=["a"],
        embeddings=[[1.0, 0.0]],
        documents=["apple pie recipe"],
        metadatas=[{"source": "cook.pdf"}],
    )
    monkeypatch.setattr(ollama_client, "embed", lambda text: [1.0, 0.0])
    out = doc_search.search("dessert")
    assert "apple pie recipe" in out
    assert "cook.pdf" in out


def test_doc_search_empty_collection(ephemeral_collection, monkeypatch):
    monkeypatch.setattr(ollama_client, "embed", lambda text: [1.0, 0.0])
    assert "No matching documents" in doc_search.search("anything")


def test_delete_by_source_removes_only_that_sources_chunks(ephemeral_collection):
    ephemeral_collection.add(
        ids=["a::0", "b::0"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["apple", "banana"],
        metadatas=[{"source": "a"}, {"source": "b"}],
    )
    vectorstore.delete_by_source("a")
    remaining = ephemeral_collection.get()
    assert remaining["metadatas"] == [{"source": "b"}]
