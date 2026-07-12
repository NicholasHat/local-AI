"""Live-model E2E coverage for the skills system: the two shipped example
skills (skills/word-count, skills/summarize-for-email) actually get invoked
through a real conversation, and self-authoring (create_skill) actually
writes a usable skill to disk.

Same live-Ollama gate as the rest of tests/e2e/ (see tests/e2e/conftest.py).
"""

import pytest

import skills

from .conftest import run_forcing_tool

pytestmark = pytest.mark.e2e


def test_word_count_skill_triggered_via_chat_e2e():
    _, reply = run_forcing_tool(
        "Use the word-count skill to count the words in this exact sentence: "
        "'the quick brown fox jumps over the lazy dog'",
        "skill__word-count",
    )
    assert "9" in reply


def test_summarize_for_email_skill_triggered_via_chat_e2e():
    conv, reply = run_forcing_tool(
        "Use the summarize-for-email skill on this text: 'so basically the "
        "server crashed at 3am, we think it was a memory leak, ops rebooted "
        "it and it's fine now but we should investigate more.' Give me the "
        "result.",
        "skill__summarize-for-email",
    )
    assert reply.strip()


@pytest.fixture
def isolated_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")
    return tmp_path / "skills"


def test_create_skill_self_authoring_e2e(isolated_skills_dir):
    run_forcing_tool(
        "Create a new skill for yourself named 'shout' that takes one "
        "argument called 'text' and instructs you to repeat the given text "
        "back in uppercase, followed by three exclamation marks. Use your "
        "create_skill tool to do this now.",
        "create_skill",
    )
    assert (isolated_skills_dir / "shout").exists()
    assert (isolated_skills_dir / "shout" / "prompt.md").exists()
    assert not (isolated_skills_dir / "shout" / "run.py").exists()

    # The newly created skill must be usable — checked as a fresh, separately
    # retried fact (not a continuation of the same conversation), since
    # whether the model reaches for a tool again right after describing what
    # it just built is a distinct, noisier judgment call than whether the
    # skill itself works.
    _, reply = run_forcing_tool(
        "Use the shout skill on the text 'hello'.", "skill__shout"
    )
    assert reply.strip()
