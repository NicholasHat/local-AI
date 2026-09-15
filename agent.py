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

from dataclasses import dataclass
from datetime import UTC, datetime

import config
import ollama_client
import skills
import spaces
from memory import Conversation
from tools import doc_search, pdf_filler, pdf_reader, web

MAX_ITERATIONS = 8

SYSTEM_PROMPT = (
    "You are a helpful local assistant with tools for PDFs, documents, the "
    "web, and shared spaces. "
    "Documents the user uploads in the sidebar are already available to you: "
    "read a whole uploaded document with read_uploaded_document(filename), and "
    "answer specific questions across uploaded documents with search_documents. "
    "Use read_pdf / list_pdf_fields / fill_pdf only for files at a filesystem "
    "path the user explicitly gives you. Never ask the user for a file path to "
    "a document they uploaded in the sidebar. Use web_search and fetch_url for "
    "current events or facts not in the documents, and read_space / "
    "post_to_space to collaborate with other agents through a shared space "
    "when given a space id. Prefer tools over guessing, and cite sources when "
    "answering from documents or the web."
)

# Tool names that reach the network (tools/web.py). Dropped from the
# advertised set when config.web_tools_enabled() is False, so an offline
# posture is a single env flag, not a code change.
WEB_TOOL_NAMES = frozenset({"web_search", "fetch_url"})


@dataclass
class RunContext:
    """Per-run facts the tools need that aren't in the user's message.

    agent_name  — who a post_to_space post is attributed to (a workflow step
                  posts as e.g. "critic @ llama3.1:latest"; chat posts as
                  "assistant").
    doc_sources — restrict search_documents to these uploaded filenames
                  (an active project's attached documents); None = all.
    system_context — extra system text sent with THIS request only (an
                  active project's goal + notes). Never persisted into the
                  conversation, so edits take effect next turn and history
                  doesn't fill with stale copies.
    """

    agent_name: str = "assistant"
    doc_sources: list[str] | None = None
    system_context: str | None = None


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
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for current information. Returns "
                "numbered results with title, URL, and snippet. Follow up with "
                "fetch_url to read a result in full."
            ),
            "parameters": _obj(
                {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "How many results (1-10, default 5).",
                    },
                },
                ["query"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch a public web page (http/https) and return its visible "
                "text, truncated. Use after web_search, or for a URL the user "
                "gives you."
            ),
            "parameters": _obj(
                {"url": {"type": "string", "description": "The page URL."}},
                ["url"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_space",
            "description": (
                "Read the latest posts in a shared communication space — a "
                "board where other agents (and the user) post. Use it to see "
                "what others have said before contributing."
            ),
            "parameters": _obj(
                {
                    "space_id": {"type": "string", "description": "The space id."},
                    "limit": {
                        "type": "integer",
                        "description": "How many recent posts to read (default 30).",
                    },
                },
                ["space_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_to_space",
            "description": (
                "Post a message into a shared communication space so other "
                "agents and the user can read it. Post conclusions, questions "
                "for other agents, or findings — not scratch work."
            ),
            "parameters": _obj(
                {
                    "space_id": {"type": "string", "description": "The space id."},
                    "content": {"type": "string", "description": "What to post."},
                },
                ["space_id", "content"],
            ),
        },
    },
]


def available_tool_schemas(names: list[str] | None = None) -> list[dict]:
    """Every tool the chat agent may advertise right now: the built-ins
    (minus the web tools when they're disabled) plus the skills discovered
    on disk this turn. `names` narrows that to an allowlist — how a workflow
    step gets exactly the tools its definition grants (plan.md decision 2,
    Phases 19–26). Unknown names are ignored, so a stale allowlist never
    crashes a run; it just advertises less."""
    schemas = TOOL_SCHEMAS + skills.tool_schemas()
    if not config.web_tools_enabled():
        schemas = [s for s in schemas if s["function"]["name"] not in WEB_TOOL_NAMES]
    if names is None:
        return schemas
    wanted = set(names)
    return [s for s in schemas if s["function"]["name"] in wanted]


def _execute_tool(name: str, args: dict, context: RunContext | None = None) -> str:
    """The single tool dispatch point. Returns a string result for the model."""
    context = context or RunContext()
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
        return doc_search.search(
            args["query"], args.get("n_results", 4), sources=context.doc_sources
        )
    if name == "create_skill":
        return skills.create_instruction_skill(
            name=args["name"],
            description=args["description"],
            parameters=args.get("parameters") or {},
            required=args.get("required") or [],
            prompt=args["prompt"],
        )
    if name == "web_search":
        return web.search(args["query"], args.get("max_results", 5))
    if name == "fetch_url":
        return web.fetch(args["url"])
    if name == "read_space":
        return spaces.render(args["space_id"], args.get("limit", 30))
    if name == "post_to_space":
        entry = spaces.post(args["space_id"], context.agent_name, args["content"])
        return f"Posted to space {args['space_id']} as {entry['author']}."
    if name.startswith("skill__"):
        return skills.execute(name, args)
    raise ValueError(f"Unknown tool: {name!r}")


# --- Loop ----------------------------------------------------------------


def _with_system_context(messages: list[dict], context: RunContext) -> list[dict]:
    """The outgoing message list: history plus, when the context carries
    system_context, one ephemeral system message right after the leading
    system prompt (or first, if there is none)."""
    if not context.system_context:
        return messages
    extra = {"role": "system", "content": context.system_context}
    at = 1 if messages and messages[0].get("role") == "system" else 0
    return messages[:at] + [extra] + messages[at:]


def run(
    user_message: str,
    conversation: Conversation,
    model: str | None = None,
    *,
    tools: list[str] | None = None,
    options: dict | None = None,
    context: RunContext | None = None,
) -> str:
    """Run one user turn through the tool-calling loop; return the reply text.

    `conversation` (memory.py) is the source of truth and is mutated in place.
    `model` overrides the default (config.OLLAMA_MODEL) for this turn only.
    `tools` is an allowlist of tool names (None = everything available),
    `options` is passed through to Ollama (temperature, num_ctx, ...), and
    `context` carries the per-run facts tools need (RunContext).
    """
    conversation.add_user(user_message)
    schemas = available_tool_schemas(tools)
    context = context or RunContext()

    for _ in range(MAX_ITERATIONS):
        message = ollama_client.chat(
            messages=_with_system_context(conversation.messages, context),
            tools=schemas,
            model=model,
            options=options,
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
                result = _execute_tool(name, args, context)
            except Exception as exc:  # feed errors back so the model can recover
                result = f"Error executing {name}: {exc}"
            conversation.add_tool_result(name, result)

    return (
        "Stopped after reaching the tool-call limit "
        f"({MAX_ITERATIONS}) without a final answer."
    )
