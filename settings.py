"""User settings that must outlive a restart (plan.md decision 9, Phases
19–26): the active provider, the active project, and the chat-model
override that the composer's picker sets. A single settings.json, read on
every access (it's tiny) so there's no cache to invalidate. Unknown keys are
rejected so a typo can't silently create a setting nothing reads."""

import json
import os
import threading
from pathlib import Path

SETTINGS_PATH = Path("settings.json")

# update() is a read-modify-write and resolve paths read on every chat turn
# and workflow step, so writes are serialized and atomic (tmp + os.replace),
# the same discipline as every other file store here.
_lock = threading.Lock()

_DEFAULTS: dict = {
    "chat_model": None,  # None = fall through to the provider / env default
    "active_provider": "default",
    "active_project": None,
}


class SettingsError(Exception):
    """Unknown setting key."""


def load() -> dict:
    data = dict(_DEFAULTS)
    if SETTINGS_PATH.exists():
        stored = json.loads(SETTINGS_PATH.read_text())
        data.update({k: v for k, v in stored.items() if k in _DEFAULTS})
    return data


def get(key: str):
    if key not in _DEFAULTS:
        raise SettingsError(f"Unknown setting: {key!r}")
    return load()[key]


def update(**changes) -> dict:
    unknown = set(changes) - set(_DEFAULTS)
    if unknown:
        raise SettingsError(f"Unknown setting(s): {sorted(unknown)}")
    with _lock:
        data = load()
        data.update(changes)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, SETTINGS_PATH)
    return data
