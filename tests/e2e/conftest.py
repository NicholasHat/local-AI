"""Session-level gate and shared helpers for the e2e suite.

Everything under tests/e2e/ requires a live, reachable Ollama with
OLLAMA_MODEL set. Rather than letting every test fail loudly when that's not
true (e.g. a plain `pytest` run in an environment with no model running),
this autouse fixture skips the whole session cleanly at the first test.
"""

import pytest

import agent
import config
import ollama_client
from memory import Conversation


@pytest.fixture(scope="session", autouse=True)
def _require_live_ollama():
    if not ollama_client.health_check():
        pytest.skip(f"Ollama is not reachable at {config.get_host()!r}.")
    try:
        config.get_model()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def new_conversation() -> Conversation:
    return Conversation(system_prompt=agent.SYSTEM_PROMPT)


def tool_names_used(conv: Conversation) -> list[str]:
    return [m["tool_name"] for m in conv.messages if m["role"] == "tool"]


def tool_content(conv: Conversation, name: str) -> str:
    for m in conv.messages:
        if m["role"] == "tool" and m["tool_name"] == name:
            return m["content"]
    raise AssertionError(
        f"tool {name!r} was never called; tools used: {tool_names_used(conv)}"
    )


def run_forcing_tool(
    prompt: str, tool_name: str, attempts: int = 3
) -> tuple[Conversation, str]:
    """Retry a live prompt a few times before failing.

    Tool-calling models don't invoke a tool 100% of the time even for a
    directive prompt — retrying the whole live call is the honest way to
    absorb that sampling noise, rather than loosening what we assert. Only
    used for tools the model chooses to call (vs. read_pdf/fill_pdf, where an
    explicit file path leaves the model no other way to answer).
    """
    last_conv: Conversation | None = None
    for _ in range(attempts):
        conv = new_conversation()
        reply = agent.run(prompt, conv)
        if tool_name in tool_names_used(conv):
            return conv, reply
        last_conv = conv
    used = tool_names_used(last_conv) if last_conv else []
    raise AssertionError(
        f"{tool_name!r} never called in {attempts} attempts; used: {used}"
    )
