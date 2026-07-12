"""End-to-end tests against a LIVE Ollama model.

Excluded from the default `pytest tests/` run (see the `e2e` marker in
pyproject.toml) and skipped automatically when Ollama isn't reachable (see
tests/e2e/conftest.py). Run explicitly with `pytest -m e2e -v`.

Assertions are intentionally loose: we check that the right tool actually
fired and that the answer reflects the tool's ground truth, never that the
model's prose matches an exact string — model wording isn't stable API
surface. PDF fixtures (text_pdf, plain_pdf, form_pdf) come from
tests/conftest.py, generated programmatically so no binaries live in the repo.
"""

import re

import pytest
from pypdf import PdfReader

import agent
import config
import ingest
import vectorstore

from .conftest import new_conversation, run_forcing_tool, tool_content, tool_names_used

pytestmark = pytest.mark.e2e


def test_get_time_e2e():
    conv, reply = run_forcing_tool(
        "What is the exact current time in UTC right now? Call your time "
        "tool rather than guessing, then tell me the hour and minute.",
        "get_time",
    )
    assert re.search(r"\d", reply)  # the model relayed *some* digits from the tool


def test_read_pdf_e2e(text_pdf):
    conv = new_conversation()
    reply = agent.run(
        f"Read the PDF at exactly this path: {text_pdf}. Quote its full text "
        "back to me verbatim.",
        conv,
    )
    assert "read_pdf" in tool_names_used(conv)
    assert "hello rag world" in reply.lower()


def test_pdf_form_fields_e2e(form_pdf, tmp_path):
    conv = new_conversation()

    agent.run(
        f"List the fillable form fields in the PDF at exactly this path: {form_pdf}",
        conv,
    )
    assert "list_pdf_fields" in tool_names_used(conv)
    assert "full_name" in tool_content(conv, "list_pdf_fields")

    out_path = tmp_path / "filled_e2e.pdf"
    agent.run(
        "Now fill the 'full_name' field with the value 'Ada Lovelace' and "
        f"save the result to exactly this path: {out_path}",
        conv,
    )
    assert "fill_pdf" in tool_names_used(conv)

    # Verify against the actual written file, not the model's account of it.
    written = PdfReader(str(out_path)).get_fields()
    assert written["full_name"].get("/V") == "Ada Lovelace"


def test_fill_refuses_non_form_pdf_e2e(plain_pdf, tmp_path):
    conv = new_conversation()
    out_path = tmp_path / "should_not_exist_e2e.pdf"
    agent.run(
        "Fill the field 'x' with value 'y' in the PDF at exactly this path: "
        f"{plain_pdf}, and save the result to exactly this path: {out_path}",
        conv,
    )
    assert "fill_pdf" in tool_names_used(conv)
    assert "no AcroForm fields" in tool_content(conv, "fill_pdf")
    assert not out_path.exists()


@pytest.fixture
def isolated_rag(tmp_path, monkeypatch):
    """Point Chroma + uploads at a throwaway tmp dir so e2e runs never touch
    the real chroma/ or uploads/ directories, and reset the cached Chroma
    client so it reconnects against the new path."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "get_chroma_path", lambda: tmp_path / "chroma")
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    vectorstore._client = None
    yield upload_dir
    vectorstore._client = None


def test_ingest_and_search_e2e(isolated_rag):
    ingest.ingest_text(
        "The secret launch code is Zebra-Quasar-77.", source="launch-notes.txt"
    )

    _, reply = run_forcing_tool(
        "Search my uploaded documents for the secret launch code and tell me "
        "exactly what it is.",
        "search_documents",
    )
    assert "zebra-quasar-77" in reply.lower()


def test_read_uploaded_document_e2e(isolated_rag, text_pdf):
    upload_dir = isolated_rag
    dest = upload_dir / "resume.pdf"
    dest.write_bytes(text_pdf.read_bytes())

    _, reply = run_forcing_tool(
        "Read the full text of the document named 'resume.pdf' that I "
        "uploaded, and quote it back to me verbatim.",
        "read_uploaded_document",
    )
    assert "hello rag world" in reply.lower()
