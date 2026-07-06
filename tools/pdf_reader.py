"""Read tool: extract text and list form fields from a PDF.

Text extraction uses pdfplumber; form-field inspection uses pypdf (AcroForm).
Both return human-readable strings — the agent feeds them straight to the model.
"""

import json
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


def read_text(path: str) -> str:
    """Raw extracted text (empty string if none). Shared by the tool below and
    by ingestion (ingest.py) — neither should sniff the tool's prose strings."""
    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages).strip()


def extract_text(path: str) -> str:
    """Tool: return the extracted text of a PDF, or a note if there is none."""
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {p}"

    text = read_text(p)
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
