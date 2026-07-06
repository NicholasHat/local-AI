"""The tool-calling loop — the heart of the app.

Loop: send history -> model returns tool_calls? -> _execute_tool() each ->
append results -> repeat -> until no tool_calls -> return final answer.
Bounded by MAX_ITERATIONS to prevent runaway loops.

Tool dispatch lives ONLY here. Add a new tool by:
  1. writing a function (real tools go in tools/),
  2. advertising its schema in TOOL_SCHEMAS,
  3. adding a case in _execute_tool().

`get_time` is the original skeleton tool; the pdf/doc tools are the real ones.
"""

from datetime import UTC, datetime

import ollama_client
from memory import Conversation
from tools import doc_search, pdf_filler, pdf_reader

MAX_ITERATIONS = 8


# --- Tools ---------------------------------------------------------------


def _get_time() -> str:
    """Skeleton tool: current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


# Schemas advertised to the model (docs/ollama-tool-calling.md request format).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current UTC time as an ISO 8601 string.",
            "parameters": _obj({}, []),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Extract and return the text content of a PDF file.",
            "parameters": _obj(
                {"path": {"type": "string", "description": "Path to the PDF."}},
                ["path"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pdf_fields",
            "description": (
                "List the fillable AcroForm field names and current values in a "
                "PDF. Call this before filling to learn the field names."
            ),
            "parameters": _obj(
                {"path": {"type": "string", "description": "Path to the PDF."}},
                ["path"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_pdf",
            "description": (
                "Fill AcroForm fields of a PDF and save a copy. `values` maps "
                "field name -> value. Fails clearly if the PDF has no form fields."
            ),
            "parameters": _obj(
                {
                    "input_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "values": {
                        "type": "object",
                        "description": "Field name -> value to write.",
                    },
                },
                ["input_path", "output_path", "values"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Semantic search over ingested documents. Use to answer "
                "questions about the user's uploaded files/notes."
            ),
            "parameters": _obj(
                {"query": {"type": "string", "description": "What to look for."}},
                ["query"],
            ),
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    """The single tool dispatch point. Returns a string result for the model."""
    if name == "get_time":
        return _get_time()
    if name == "read_pdf":
        return pdf_reader.extract_text(args["path"])
    if name == "list_pdf_fields":
        return pdf_reader.list_fields(args["path"])
    if name == "fill_pdf":
        return pdf_filler.fill(args["input_path"], args["output_path"], args["values"])
    if name == "search_documents":
        return doc_search.search(args["query"], args.get("n_results", 4))
    raise ValueError(f"Unknown tool: {name!r}")


# --- Loop ----------------------------------------------------------------


def run(user_message: str, conversation: Conversation) -> str:
    """Run one user turn through the tool-calling loop; return the reply text.

    `conversation` (memory.py) is the source of truth and is mutated in place.
    """
    conversation.add_user(user_message)

    for _ in range(MAX_ITERATIONS):
        message = ollama_client.chat(messages=conversation.messages, tools=TOOL_SCHEMAS)
        conversation.add_assistant(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return message.get("content", "")

        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            try:
                result = _execute_tool(name, args)
            except Exception as exc:  # feed errors back so the model can recover
                result = f"Error executing {name}: {exc}"
            conversation.add_tool_result(name, result)

    return (
        "Stopped after reaching the tool-call limit "
        f"({MAX_ITERATIONS}) without a final answer."
    )
