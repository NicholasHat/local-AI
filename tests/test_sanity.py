"""Phase 1 sanity checks: package imports and config loading work."""

import config


def test_imports():
    import agent
    import memory
    import ollama_client
    import tools

    assert agent and memory and ollama_client and tools


def test_embed_model_has_default():
    assert config.get_embed_model() == "nomic-embed-text"


def test_host_has_default():
    assert config.get_host().startswith("http")


def test_model_requires_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    try:
        config.get_model()
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "get_model() must raise when OLLAMA_MODEL is unset"
