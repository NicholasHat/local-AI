"""The tool-calling loop — the heart of the app.

Loop: send history -> model returns tool_calls? -> _execute_tool() each ->
append results -> repeat -> until no tool_calls -> return final answer.
Bounded by MAX_ITERATIONS to prevent runaway loops.

Tool dispatch lives ONLY here. Add a new tool by:
  1. writing a function (real tools go in tools/),
  2. advertising its schema in TOOL_SCHEMAS,
  3. adding a case in _execute_tool().

The second way to add a tool is a skill (skills.py) — a file on disk under
skills/<name>/, discovered fresh each turn and dispatched via the one
`skill__` case below, with no code change here required.

`get_time` is the original skeleton tool; the pdf/doc tools are the real ones.
"""

from datetime import UTC, datetime

import ollama_client
import skills
from memory import Conversation
from tools import doc_search, pdf_filler, pdf_reader

MAX_ITERATIONS = 8

SYSTEM_PROMPT = (
    "You are a helpful local assistant with tools for PDFs and documents. "
    "Documents the user uploads in the sidebar are already available to you: "
    "read a whole uploaded document with read_uploaded_document(filename), and "
    "answer specific questions across uploaded documents with search_documents. "
    "Use read_pdf / list_pdf_fields / fill_pdf only for files at a filesystem "
    "path the user explicitly gives you. Never ask the user for a file path to "
    "a document they uploaded in the sidebar. Prefer tools over guessing, and "
    "cite sources when answering from documents."
)


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
            "name": "read_uploaded_document",
            "description": (
                "Return the FULL text of a document the user uploaded through "
                "the app sidebar. Use this for whole-document tasks such as "
                "summarizing or analyzing an entire resume. The argument is the "
                "filename shown in the sidebar, NOT a filesystem path. Never ask "
                "the user for a path to a document they uploaded here."
            ),
            "parameters": _obj(
                {
                    "filename": {
                        "type": "string",
                        "description": "The uploaded file's name (from the sidebar).",
                    }
                },
                ["filename"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": (
                "Extract the text of a PDF located at a filesystem path the user "
                "explicitly provided. Do NOT use this for files uploaded in the "
                "sidebar — use read_uploaded_document instead."
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
                "Semantic search over uploaded documents; returns the most "
                "relevant snippets. Best for answering a specific question across "
                "documents. To read/analyze an entire uploaded document, use "
                "read_uploaded_document instead."
            ),
            "parameters": _obj(
                {"query": {"type": "string", "description": "What to look for."}},
                ["query"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": (
                "Create a new INSTRUCTION skill for yourself: a reusable prompt "
                "template you will follow whenever this skill is invoked again. "
                "Use this when the user asks you to build yourself a new "
                "capability made of instructions (e.g. 'make yourself a skill "
                "that rewrites text as a formal email'). This can only create "
                "instruction-based skills — it can never make a skill that runs "
                "code; that requires a human authoring it directly."
            ),
            "parameters": _obj(
                {
                    "name": {
                        "type": "string",
                        "description": "Slug name: lowercase letters/digits/hyphens.",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the skill does, for the tool list.",
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            'JSON-schema "properties" for the skill\'s arguments, '
                            'e.g. {"text": {"type": "string"}}.'
                        ),
                    },
                    "required": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which of those argument names are required.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "The instruction template, with {argument_name} "
                            "placeholders for each parameter."
                        ),
                    },
                },
                ["name", "description", "prompt"],
            ),
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    """The single tool dispatch point. Returns a string result for the model."""
    if name == "get_time":
        return _get_time()
    if name == "read_uploaded_document":
        return pdf_reader.read_uploaded_document(args["filename"])
    if name == "read_pdf":
        return pdf_reader.extract_text(args["path"])
    if name == "list_pdf_fields":
        return pdf_reader.list_fields(args["path"])
    if name == "fill_pdf":
        return pdf_filler.fill(args["input_path"], args["output_path"], args["values"])
    if name == "search_documents":
        return doc_search.search(args["query"], args.get("n_results", 4))
    if name == "create_skill":
        return skills.create_instruction_skill(
            name=args["name"],
            description=args["description"],
            parameters=args.get("parameters") or {},
            required=args.get("required") or [],
            prompt=args["prompt"],
        )
    if name.startswith("skill__"):
        return skills.execute(name, args)
    raise ValueError(f"Unknown tool: {name!r}")


# --- Loop ----------------------------------------------------------------


def run(user_message: str, conversation: Conversation, model: str | None = None) -> str:
    """Run one user turn through the tool-calling loop; return the reply text.

    `conversation` (memory.py) is the source of truth and is mutated in place.
    `model` overrides the default (config.OLLAMA_MODEL) for this turn only.
    """
    conversation.add_user(user_message)
    tools = TOOL_SCHEMAS + skills.tool_schemas()

    for _ in range(MAX_ITERATIONS):
        message = ollama_client.chat(
            messages=conversation.messages, tools=tools, model=model
        )
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
