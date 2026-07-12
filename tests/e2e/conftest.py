"""Session-level gate for the e2e suite.

Everything under tests/e2e/ requires a live, reachable Ollama with
OLLAMA_MODEL set. Rather than letting every test fail loudly when that's not
true (e.g. a plain `pytest` run in an environment with no model running),
this autouse fixture skips the whole session cleanly at the first test.
"""

import pytest

import config
import ollama_client


@pytest.fixture(scope="session", autouse=True)
def _require_live_ollama():
    if not ollama_client.health_check():
        pytest.skip(f"Ollama is not reachable at {config.get_host()!r}.")
    try:
        config.get_model()
    except RuntimeError as exc:
        pytest.skip(str(exc))
