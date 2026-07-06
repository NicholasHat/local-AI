"""Shared PDF fixtures, built programmatically so no binaries live in the repo."""

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


@pytest.fixture
def text_pdf(tmp_path):
    """A one-page PDF containing the text 'Hello RAG world'."""
    path = tmp_path / "text.pdf"
    w = PdfWriter()
    w.add_blank_page(width=300, height=300)
    page = w.pages[0]
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 18 Tf 40 150 Td (Hello RAG world) Tj ET")
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Contents")] = w._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): w._add_object(font)}
            )
        }
    )
    with path.open("wb") as fh:
        w.write(fh)
    return path


@pytest.fixture
def plain_pdf(tmp_path):
    """A blank PDF with NO form fields (the pypdf silent-success trap)."""
    path = tmp_path / "plain.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with path.open("wb") as fh:
        w.write(fh)
    return path


@pytest.fixture
def form_pdf(tmp_path):
    """A PDF with one fillable AcroForm text field named 'full_name'."""
    path = tmp_path / "form.pdf"
    w = PdfWriter()
    w.add_blank_page(width=300, height=300)
    page = w.pages[0]

    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("full_name"),
            NameObject("/V"): TextStringObject(""),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(v) for v in (50, 200, 250, 220)]
            ),
            NameObject("/F"): NumberObject(4),
        }
    )
    ref = w._add_object(field)
    field[NameObject("/P")] = page.indirect_reference
    page[NameObject("/Annots")] = ArrayObject([ref])

    acro = DictionaryObject(
        {
            NameObject("/Fields"): ArrayObject([ref]),
            NameObject("/NeedAppearances"): BooleanObject(True),
        }
    )
    w._root_object[NameObject("/AcroForm")] = w._add_object(acro)

    with path.open("wb") as fh:
        w.write(fh)
    return path
