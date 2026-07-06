"""Conversation history — the source of truth (NOT Streamlit session state).

Message schema follows Ollama's tool-calling format (see
docs/ollama-tool-calling.md):

    {"role": "system", "content": ...}
    {"role": "user", "content": ...}
    {"role": "assistant", "content": ..., "tool_calls": [...]}   # tool_calls optional
    {"role": "tool", "tool_name": ..., "content": ...}           # a tool result

Invariant: an assistant message carrying `tool_calls` and the `tool` result
message(s) that answer it must stay together — any future trimming/context
management must never drop one without the other.
"""


class Conversation:
    def __init__(self, system_prompt: str | None = None):
        self._messages: list[dict] = []
        if system_prompt:
            self._messages.append({"role": "system", "content": system_prompt})

    @property
    def messages(self) -> list[dict]:
        """A copy of the history, ready to pass to ollama_client.chat()."""
        return list(self._messages)

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant(self, message: dict) -> None:
        """Store an assistant message as returned by ollama_client.chat().

        Ollama's response dump carries null extras (thinking/images/tool_name);
        strip None-valued keys so re-sent history stays clean. Keeps tool_calls
        when present.
        """
        clean = {k: v for k, v in message.items() if v is not None}
        clean["role"] = "assistant"
        self._messages.append(clean)

    def add_tool_result(self, tool_name: str, content: str) -> None:
        """Append a tool result, matched to its call by tool_name."""
        self._messages.append(
            {"role": "tool", "tool_name": tool_name, "content": str(content)}
        )
