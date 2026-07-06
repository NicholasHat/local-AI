"""Tests for the PDF read/fill tools, using programmatic PDF fixtures."""

import json

from pypdf import PdfReader

from tools import pdf_filler, pdf_reader


def test_extract_text(text_pdf):
    assert pdf_reader.extract_text(str(text_pdf)) == "Hello RAG world"


def test_extract_text_missing_file(tmp_path):
    out = pdf_reader.extract_text(str(tmp_path / "nope.pdf"))
    assert "not found" in out


def test_extract_text_no_text(plain_pdf):
    assert "No extractable text" in pdf_reader.extract_text(str(plain_pdf))


def test_list_fields_on_form(form_pdf):
    out = json.loads(pdf_reader.list_fields(str(form_pdf)))
    assert "full_name" in out


def test_list_fields_on_plain(plain_pdf):
    assert "no fillable form fields" in pdf_reader.list_fields(str(plain_pdf))


def test_fill_form_writes_value(form_pdf, tmp_path):
    out_path = tmp_path / "filled.pdf"
    msg = pdf_filler.fill(str(form_pdf), str(out_path), {"full_name": "Ada Lovelace"})
    assert "Filled 1 field" in msg

    written = PdfReader(str(out_path)).get_fields()
    assert written["full_name"].get("/V") == "Ada Lovelace"


def test_fill_refuses_non_form_pdf(plain_pdf, tmp_path):
    """The CLAUDE.md gotcha: must NOT silently succeed on a non-form PDF."""
    out_path = tmp_path / "should_not_exist.pdf"
    msg = pdf_filler.fill(str(plain_pdf), str(out_path), {"x": "y"})
    assert "no AcroForm fields" in msg
    assert not out_path.exists()  # nothing written


def test_fill_rejects_unknown_field(form_pdf, tmp_path):
    out_path = tmp_path / "filled.pdf"
    msg = pdf_filler.fill(str(form_pdf), str(out_path), {"nonexistent": "z"})
    assert "unknown field" in msg
    assert not out_path.exists()
