"""catalog.py: seed validation, library shape, installed merging, and the
two live feeds with urllib mocked — no network, no Ollama."""

import hashlib
import json
import urllib.error

import pytest

import catalog


@pytest.fixture(autouse=True)
def clear_cache():
    catalog._cache.clear()
    yield
    catalog._cache.clear()


def test_seed_parses_and_validates_shipped_catalog():
    data = catalog.seed()
    assert data["updated"] == "2026-09-15"
    assert data["errors"] == []
    names = {m["name"] for m in data["models"]}
    assert {"qwen2.5", "llama3.1", "nomic-embed-text"} <= names
    for m in data["models"]:
        assert m["category"] in catalog._CATEGORIES
        assert m["ollama_tags"] and all(t["tag"] for t in m["ollama_tags"])


def test_seed_skips_bad_entries_without_raising(tmp_path, monkeypatch):
    path = tmp_path / "catalog.yaml"
    path.write_text(
        "updated: '2026-01-01'\nmodels:\n"
        "  - {name: good, category: general, ollama_tags: [{tag: 'good:1b'}]}\n"
        "  - {name: bad-cat, category: nope, ollama_tags: [{tag: 'x'}]}\n"
        "  - {name: no-tags, category: small}\n"
        "  - {category: general, ollama_tags: [{tag: 'x'}]}\n"
    )
    monkeypatch.setattr(catalog, "CATALOG_PATH", path)
    data = catalog.seed()
    assert [m["name"] for m in data["models"]] == ["good"]
    assert len(data["errors"]) == 3
    assert any("bad-cat" in e for e in data["errors"])


def test_library_is_recommended_families_by_bare_name():
    rows = catalog.library()
    assert rows and all(set(r) == {"name", "description", "tool_capable"} for r in rows)
    by_name = {r["name"]: r for r in rows}
    assert by_name["qwen2.5"]["tool_capable"] is True
    assert by_name["nomic-embed-text"]["tool_capable"] is False
    assert "mixtral" not in by_name  # not recommended


def test_catalog_marks_installed_by_tag_and_family():
    installed = [
        {"name": "qwen2.5:latest", "size": 1, "digest": None, "capabilities": []},
        {"name": "llama3.2:1b", "size": 1, "digest": None, "capabilities": []},
        {
            "name": "nomic-embed-text:latest",
            "size": 1,
            "digest": None,
            "capabilities": [],
        },
    ]
    data = catalog.catalog(installed)
    by_name = {m["name"]: m for m in data["models"]}
    assert by_name["qwen2.5"]["installed_any"] is True
    assert by_name["qwen2.5"]["installed_tags"] == ["qwen2.5:latest"]
    llama = by_name["llama3.2"]
    assert next(t for t in llama["ollama_tags"] if t["tag"] == "llama3.2:1b")[
        "installed"
    ]
    assert not next(t for t in llama["ollama_tags"] if t["tag"] == "llama3.2:3b")[
        "installed"
    ]
    nomic_tag = by_name["nomic-embed-text"]["ollama_tags"][0]
    assert nomic_tag["installed"] is True  # :latest matches the tagged install
    assert by_name["mistral"]["installed_any"] is False


def test_trending_maps_hf_rows_to_pull_tags(monkeypatch):
    rows = [
        {
            "id": "unsloth/Qwen3-8B-GGUF",
            "likes": 5,
            "downloads": 10,
            "trendingScore": 42,
            "pipeline_tag": "text-generation",
            "tags": ["gguf", "license:apache-2.0"],
            "createdAt": "2026-01-01T00:00:00.000Z",
        },
        {"modelId": "org/other", "tags": []},
    ]
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return json.dumps(rows).encode()

    monkeypatch.setattr(catalog, "_fetch", fake_fetch)
    out = catalog.trending(limit=5)
    assert "limit=5" in calls[0] and "filter=gguf" in calls[0]
    assert out["entries"][0]["pull_tag"] == "hf.co/unsloth/Qwen3-8B-GGUF"
    assert out["entries"][0]["license"] == "apache-2.0"
    assert out["entries"][1] == {
        "repo": "org/other",
        "pull_tag": "hf.co/org/other",
        "likes": 0,
        "downloads": 0,
        "trending_score": 0,
        "pipeline": "",
        "license": "",
        "created_at": "",
    }
    # cached: a second call doesn't hit the network; refresh does
    catalog.trending(limit=5)
    assert len(calls) == 1
    catalog.trending(limit=5, refresh=True)
    assert len(calls) == 2


def test_trending_offline_returns_error_not_exception(monkeypatch):
    def fail(url):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(catalog, "_fetch", fail)
    out = catalog.trending()
    assert out["offline"] is True and "no network" in out["error"]
    assert "trending:20" not in catalog._cache  # errors are never cached


def test_check_updates_compares_manifest_hash(monkeypatch):
    remote = b'{"schemaVersion":2,"layers":[]}'
    monkeypatch.setattr(catalog, "_fetch", lambda url: remote)
    same = hashlib.sha256(remote).hexdigest()
    installed = [
        {"name": "qwen2.5:latest", "digest": same},
        {"name": "llama3.2:1b", "digest": "0" * 64},
        {"name": "hf.co/org/repo:Q4", "digest": same},
    ]
    out = catalog.check_updates(installed)
    statuses = {m["name"]: m["status"] for m in out["models"]}
    assert statuses == {
        "qwen2.5:latest": "up_to_date",
        "llama3.2:1b": "update_available",
        "hf.co/org/repo:Q4": "skipped",
    }
    assert out["models"][1]["remote_digest"] == same


def test_check_updates_hashes_local_manifest_when_digest_missing(tmp_path, monkeypatch):
    manifest = b'{"local": true}'
    path = (
        tmp_path / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5" / "latest"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(manifest)
    monkeypatch.setattr(catalog.config, "get_ollama_models_dir", lambda: tmp_path)
    monkeypatch.setattr(catalog, "_fetch", lambda url: manifest)
    out = catalog.check_updates([{"name": "qwen2.5", "digest": None}])
    assert out["models"][0]["status"] == "up_to_date"


def test_check_updates_registry_unreachable_is_unknown(monkeypatch):
    def fail(url):
        raise TimeoutError("slow")

    monkeypatch.setattr(catalog, "_fetch", fail)
    out = catalog.check_updates([{"name": "qwen2.5:latest", "digest": "abc"}])
    assert out["models"][0]["status"] == "unknown"
    assert "slow" in out["models"][0]["reason"]
