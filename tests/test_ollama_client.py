"""Unit tests for the thin wrapper. The underlying ollama Client is mocked,
so these run with no Ollama server."""

from types import SimpleNamespace

import ollama_client


class _FakeClient:
    """Records calls and returns canned ollama-shaped responses."""

    def __init__(self):
        self.chat_kwargs = None
        self.embed_kwargs = None
        self.list_called = False

    def chat(self, **kwargs):
        self.chat_kwargs = kwargs
        message = SimpleNamespace(
            model_dump=lambda: {
                "role": "assistant",
                "content": "hi",
                "tool_calls": None,
            }
        )
        return SimpleNamespace(message=message)

    def embed(self, **kwargs):
        self.embed_kwargs = kwargs
        return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    def list(self):
        self.list_called = True
        return {"models": []}


def _install_fake(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(ollama_client, "_get_client", lambda: fake)
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    return fake


def test_chat_passes_args_and_returns_dict(monkeypatch):
    fake = _install_fake(monkeypatch)
    msg = ollama_client.chat(
        messages=[{"role": "user", "content": "hey"}],
        tools=[{"type": "function"}],
    )
    assert msg == {"role": "assistant", "content": "hi", "tool_calls": None}
    assert fake.chat_kwargs["model"] == "test-model"
    assert fake.chat_kwargs["stream"] is False
    assert fake.chat_kwargs["tools"] == [{"type": "function"}]


def test_chat_explicit_model_overrides_env(monkeypatch):
    fake = _install_fake(monkeypatch)
    ollama_client.chat(messages=[], model="other")
    assert fake.chat_kwargs["model"] == "other"


def test_embed_returns_first_vector(monkeypatch):
    fake = _install_fake(monkeypatch)
    vec = ollama_client.embed("some text")
    assert vec == [0.1, 0.2, 0.3]
    assert fake.embed_kwargs["input"] == "some text"
    assert fake.embed_kwargs["model"] == "nomic-embed-text"


def test_health_check_true_when_reachable(monkeypatch):
    fake = _install_fake(monkeypatch)
    assert ollama_client.health_check() is True
    assert fake.list_called


def test_health_check_false_on_error(monkeypatch):
    def boom():
        raise ConnectionError("no server")

    monkeypatch.setattr(
        ollama_client, "_get_client", lambda: SimpleNamespace(list=boom)
    )
    assert ollama_client.health_check() is False
