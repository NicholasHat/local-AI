"""Live smoke test for ollama_client — needs a running Ollama + pulled models.

    ollama serve
    ollama pull qwen2.5 && ollama pull nomic-embed-text
    OLLAMA_MODEL=qwen2.5 python scripts/smoke_ollama.py

Not run by pytest; this is the Phase 2 definition-of-done check against a real
server.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ollama_client  # noqa: E402


def main() -> int:
    if not ollama_client.health_check():
        print("FAIL: Ollama not reachable at the configured host.")
        return 1
    print("OK: Ollama reachable.")

    msg = ollama_client.chat(messages=[{"role": "user", "content": "Say hi."}])
    print(f"OK: chat replied -> {msg.get('content')!r}")

    vec = ollama_client.embed("hello world")
    print(f"OK: embed returned a {len(vec)}-dim vector.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
