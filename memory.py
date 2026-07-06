"""Conversation history — the source of truth (NOT Streamlit session state).

Message schema follows Ollama's tool-calling format (see
docs/ollama-tool-calling.md): assistant messages may carry `tool_calls`;
results come back as `{"role": "tool", "content": ..., "tool_name": ...}`.
A tool call and its result must always be kept together — never trim one
without the other.

Implemented in Phase 3.
"""
