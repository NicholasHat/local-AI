"""Phase 4 definition of done: the agent can invoke each real tool via
_execute_tool()."""

import chromadb

import agent
import config
import ollama_client
import skills
import vectorstore


def test_dispatch_read_pdf(text_pdf):
    assert agent._execute_tool("read_pdf", {"path": str(text_pdf)}) == "Hello RAG world"


def test_dispatch_read_uploaded_document(text_pdf, monkeypatch):
    monkeypatch.setattr(config, "get_upload_dir", lambda: text_pdf.parent)
    out = agent._execute_tool("read_uploaded_document", {"filename": text_pdf.name})
    assert out == "Hello RAG world"


def test_dispatch_list_pdf_fields(form_pdf):
    out = agent._execute_tool("list_pdf_fields", {"path": str(form_pdf)})
    assert "full_name" in out


def test_dispatch_fill_pdf(form_pdf, tmp_path):
    out_path = tmp_path / "filled.pdf"
    msg = agent._execute_tool(
        "fill_pdf",
        {
            "input_path": str(form_pdf),
            "output_path": str(out_path),
            "values": {"full_name": "Grace Hopper"},
        },
    )
    assert "Filled 1 field" in msg
    assert out_path.exists()


def test_dispatch_search_documents(monkeypatch):
    col = chromadb.EphemeralClient().get_or_create_collection("dispatch_docs")
    col.add(
        ids=["a"],
        embeddings=[[1.0, 0.0]],
        documents=["the answer is 42"],
        metadatas=[{"source": "notes.txt"}],
    )
    monkeypatch.setattr(vectorstore, "get_collection", lambda: col)
    monkeypatch.setattr(ollama_client, "embed", lambda text: [1.0, 0.0])
    out = agent._execute_tool("search_documents", {"query": "answer"})
    assert "the answer is 42" in out


def test_dispatch_create_skill_then_invoke_it(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")

    msg = agent._execute_tool(
        "create_skill",
        {
            "name": "greet",
            "description": "Greets someone",
            "parameters": {"name": {"type": "string"}},
            "required": ["name"],
            "prompt": "Say hello to {name}.",
        },
    )
    assert "greet" in msg

    out = agent._execute_tool("skill__greet", {"name": "Ada"})
    assert out == "Say hello to Ada."
