"""Fill tool: write values into a PDF's AcroForm fields with pypdf.

CLAUDE.md gotcha: pypdf silently succeeds on a non-form PDF — it writes an
output file but fills nothing. So we ALWAYS call get_fields() first and refuse
(with a clear message) when there are no fields, rather than producing a
deceptively "successful" empty result.
"""

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def fill(input_path: str, output_path: str, values: dict) -> str:
    """Fill AcroForm fields in `input_path` with `values`, writing to
    `output_path`. Returns a status string."""
    src = Path(input_path)
    if not src.exists():
        return f"Error: file not found: {src}"

    reader = PdfReader(str(src))
    fields = reader.get_fields()  # <-- guard: check BEFORE writing
    if not fields:
        return (
            f"Error: '{src.name}' has no AcroForm fields to fill. pypdf would "
            "write an output file without filling anything, so nothing was done."
        )

    unknown = [name for name in values if name not in fields]
    if unknown:
        return f"Error: unknown field(s) {unknown}. Available fields: {sorted(fields)}"

    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)

    out = Path(output_path)
    with out.open("wb") as fh:
        writer.write(fh)

    return f"Filled {len(values)} field(s) and wrote '{out}'."
