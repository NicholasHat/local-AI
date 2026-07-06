"""The tool-calling loop — the heart of the app.

Loop: send history -> model returns tool_calls? -> _execute_tool() each ->
append results -> repeat -> until no tool_calls -> return final answer.
Bounded by a hard max-iteration guard to prevent runaway loops.

Tool dispatch lives ONLY here. Add a new tool by writing a function in
tools/ and adding a case in _execute_tool().

Implemented in Phase 3.
"""

MAX_ITERATIONS = 8


def _execute_tool(name, args):
    """The single tool dispatch point."""
    raise NotImplementedError("Phase 3")


def run(user_message):
    """Run one user turn through the tool-calling loop; return the reply."""
    raise NotImplementedError("Phase 3")
