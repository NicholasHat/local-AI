"""providers.py — routing profiles and the recommendation (Phase 21)."""

import pytest

import providers
import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "PROVIDERS_DIR", tmp_path / "providers")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "env-embed")


def test_default_provider_resolves_to_env():
    assert [p.name for p in providers.discover()] == ["default"]
    assert providers.resolve("chat") == "env-model"
    assert providers.resolve("coding") == "env-model"
    assert providers.resolve("embedding") == "env-embed"


def test_resolution_order():
    providers.save("mine", "d", {"chat": "routed", "coding": "coder"})
    providers.activate("mine")
    assert providers.resolve("chat") == "routed"
    assert providers.resolve("coding") == "coder"
    assert providers.resolve("judge") == "env-model"  # falls through
    settings.update(chat_model="session")
    assert providers.resolve("chat") == "session"
    assert providers.resolve("coding") == "coder"  # session override is chat-only
    assert providers.resolve("chat", override="explicit") == "explicit"


def test_activate_clears_session_override():
    providers.save("mine", "d", {"chat": "routed"})
    settings.update(chat_model="session")
    providers.activate("mine")
    assert settings.get("chat_model") is None
    assert providers.resolve("chat") == "routed"


def test_save_validates():
    with pytest.raises(providers.ProviderError):
        providers.save("default", "d", {})
    with pytest.raises(providers.ProviderError):
        providers.save("Bad Name", "d", {})
    with pytest.raises(providers.ProviderError):
        providers.save("x", "d", {"pilot": "m"})
    with pytest.raises(providers.ProviderError):
        providers.save("x", "d", {"chat": "m"}, {"chat": "not-a-mapping"})


def test_delete_falls_back_to_default():
    providers.save("mine", "d", {"chat": "m"})
    providers.activate("mine")
    providers.delete("mine")
    assert providers.active().name == "default"
    with pytest.raises(providers.ProviderError):
        providers.get("mine")


def test_malformed_file_is_skipped(tmp_path):
    providers.PROVIDERS_DIR.mkdir()
    (providers.PROVIDERS_DIR / "broken.yaml").write_text("routes: [not, a, map]")
    assert [p.name for p in providers.discover()] == ["default"]


def test_unknown_role():
    with pytest.raises(providers.ProviderError):
        providers.resolve("pilot")


def _row(model, tool_capable, overall, cats, tps):
    return {
        "model": model,
        "tool_capable": tool_capable,
        "overall": overall,
        "categories": cats,
        "tokens_per_sec": tps,
    }


def test_recommend_picks_best_per_role_and_requires_tools_for_agentic():
    board = [
        _row(
            "big-no-tools",
            False,
            0.9,
            {"reasoning": 1.0, "coding": 1.0, "instruction": 1.0, "knowledge": 1.0},
            10,
        ),
        _row(
            "mid-tools",
            True,
            0.7,
            {"reasoning": 0.6, "coding": 0.8, "instruction": 0.7, "tools": 0.9},
            20,
        ),
        _row("tiny", True, 0.5, {"reasoning": 0.4, "coding": 0.5}, 200),
    ]
    rec = providers.recommend(board)
    assert rec.routes["chat"] == "mid-tools"
    assert rec.routes["coding"] == "mid-tools"
    assert rec.routes["judge"] == "big-no-tools"  # judge needn't call tools
    assert rec.routes["fast"] == "tiny"  # fastest with overall >= best/2


def test_recommend_restricts_to_installed_and_errors_when_empty():
    board = [_row("gone", True, 0.9, {"reasoning": 1.0}, 5)]
    with pytest.raises(providers.ProviderError):
        providers.recommend(board, installed={"other"})
    with pytest.raises(providers.ProviderError):
        providers.recommend([])
