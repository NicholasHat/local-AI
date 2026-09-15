"""settings.py — persisted user settings (Phase 19)."""

import pytest

import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")


def test_defaults_without_file():
    assert settings.get("active_provider") == "default"
    assert settings.get("chat_model") is None
    assert settings.get("active_project") is None


def test_update_persists_and_merges():
    settings.update(chat_model="qwen2.5:latest")
    settings.update(active_project="p1")
    assert settings.load() == {
        "chat_model": "qwen2.5:latest",
        "active_provider": "default",
        "active_project": "p1",
    }


def test_unknown_keys_rejected():
    with pytest.raises(settings.SettingsError):
        settings.update(bogus=1)
    with pytest.raises(settings.SettingsError):
        settings.get("bogus")


def test_unknown_stored_keys_are_ignored(tmp_path):
    settings.SETTINGS_PATH.write_text('{"chat_model": "x", "stale": true}')
    assert settings.load()["chat_model"] == "x"
    assert "stale" not in settings.load()
