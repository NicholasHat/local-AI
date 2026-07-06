"""The tool-calling loop — the heart of the app.

Loop: send history -> model returns tool_calls? -> _execute_tool() each ->
append results -> repeat -> until no tool_calls -> return final answer.
Bounded by MAX_ITERATIONS to prevent runaway loops.

Tool dispatch lives ONLY here. Add a new tool by:
  1. writing a function (real tools go in tools/, Phase 4+),
  2. advertising its schema in TOOL_SCHEMAS,
  3. adding a case in _execute_tool().

`get_time` below is the Phase 3 skeleton tool that proves the cycle; Phase 4
replaces/augments it with the real pdf/doc tools.
"""

from datetime import UTC, datetime

import ollama_client
from memory import Conversation

MAX_ITERATIONS = 8


# --- Tools ---------------------------------------------------------------


def _get_time() -> str:
    """Skeleton tool: current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# Schemas advertised to the model (docs/ollama-tool-calling.md request format).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current UTC time as an ISO 8601 string.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    """The single tool dispatch point. Returns a string result for the model."""
    if name == "get_time":
        return _get_time()
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
