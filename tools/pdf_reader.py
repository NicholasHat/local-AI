"""Read tool: extract text and list form fields from a PDF.

Text extraction uses pdfplumber; form-field inspection uses pypdf (AcroForm).
Both return human-readable strings — the agent feeds them straight to the model.
"""

import json
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


def extract_text(path: str) -> str:
    """Return the extracted text of a PDF, or a note if there is none."""
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {p}"

    with pdfplumber.open(str(p)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n\n".join(pages).strip()

    if not text:
        return "(No extractable text — the PDF is likely scanned images; OCR needed.)"
    return text


def list_fields(path: str) -> str:
    """Return the fillable AcroForm fields (name -> current value) as JSON."""
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {p}"

    fields = PdfReader(str(p)).get_fields()
    if not fields:
        return "This PDF has no fillable form fields (not an AcroForm)."

    current = {name: (obj.get("/V") or "") for name, obj in fields.items()}
    return json.dumps(current, indent=2, default=str)
