"""Contract tests for api/models.py with ollama_client, catalog feeds, and
the vault mocked/isolated — no Ollama, no network."""

import pytest
from fastapi.testclient import TestClient

import catalog
import config
import ollama_client
import server
import vault

_INSTALLED = [
    {"name": "qwen2.5:latest", "size": 100, "digest": "abc", "capabilities": ["tools"]},
    {
        "name": "nomic-embed-text:latest",
        "size": 5,
        "digest": "def",
        "capabilities": ["embedding"],
    },
]


def _details(name):
    return {
        "name": name,
        "family": "qwen2",
        "families": ["qwen2"],
        "parameter_size": "7.6B",
        "quantization_level": "Q4_K_M",
        "format": "gguf",
        "architecture": "qwen2",
        "context_length": 32768,
        "parameter_count": 7_600_000_000,
        "license": "Apache License",
        "license_link": "",
        "base_model": "",
        "capabilities": ["tools"],
        "modified_at": "2026-01-01T00:00:00",
        "template": "{{ .Prompt }}",
        "system": "",
        "parameters": "",
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_client, "list_models", lambda: list(_INSTALLED))
    monkeypatch.setattr(ollama_client, "show_model", _details)
    monkeypatch.setattr(
        ollama_client,
        "running_models",
        lambda: [
            {"name": "qwen2.5:latest", "size": 1, "size_vram": 1, "expires_at": None}
        ],
    )
    monkeypatch.setattr(config, "get_vault_dir", lambda: tmp_path / "vault")
    monkeypatch.setattr(config, "get_ollama_models_dir", lambda: tmp_path / "models")
    catalog._cache.clear()
    return TestClient(server.app)


def test_library_comes_from_catalog(client):
    rows = client.get("/api/models/library").json()
    assert {"name", "description", "tool_capable"} == set(rows[0])
    assert any(r["name"] == "qwen2.5" for r in rows)


def test_installed_merges_details_running_and_tool_capability(client):
    rows = client.get("/api/models/installed").json()
    qwen = next(r for r in rows if r["name"] == "qwen2.5:latest")
    assert qwen["running"] is True and qwen["tool_capable"] is True
    assert qwen["context_length"] == 32768 and qwen["digest"] == "abc"
    nomic = next(r for r in rows if r["name"] == "nomic-embed-text:latest")
    assert nomic["running"] is False and nomic["tool_capable"] is False

    one = client.get("/api/models/installed/qwen2.5:latest")
    assert one.status_code == 200 and one.json()["parameter_size"] == "7.6B"
    assert client.get("/api/models/installed/hf.co/org/repo:Q4").status_code == 404


def test_running(client):
    assert client.get("/api/models/running").json()[0]["name"] == "qwen2.5:latest"


def test_catalog_flags_installed(client):
    data = client.get("/api/models/catalog").json()
    assert data["updated"] and data["errors"] == []
    qwen = next(m for m in data["models"] if m["name"] == "qwen2.5")
    assert qwen["installed_any"] is True and qwen["installed_tags"] == [
        "qwen2.5:latest"
    ]


def test_trending_and_updates_pass_through_and_survive_offline(client, monkeypatch):
    monkeypatch.setattr(
        catalog,
        "trending",
        lambda limit=20, refresh=False: {
            "entries": [
                {
                    "repo": "o/r",
                    "pull_tag": "hf.co/o/r",
                    "likes": 1,
                    "downloads": 2,
                    "trending_score": 3,
                    "pipeline": "",
                    "license": "",
                    "created_at": "",
                }
            ],
            "fetched_at": "now",
        },
    )
    body = client.get("/api/models/trending?limit=1").json()
    assert body["entries"][0]["pull_tag"] == "hf.co/o/r" and body["error"] is None

    monkeypatch.setattr(
        catalog,
        "trending",
        lambda limit=20, refresh=False: {"error": "down", "offline": True},
    )
    body = client.get("/api/models/trending").json()
    assert body == {"entries": [], "fetched_at": None, "error": "down", "offline": True}

    monkeypatch.setattr(
        catalog,
        "check_updates",
        lambda installed, refresh=False: {
            "models": [{"name": m["name"], "status": "up_to_date"} for m in installed],
            "checked_at": "now",
        },
    )
    body = client.get("/api/models/updates").json()
    assert [m["status"] for m in body["models"]] == ["up_to_date", "up_to_date"]


def test_create_model(client, monkeypatch):
    captured = {}

    def fake_create(name, from_model, system=None, parameters=None, template=None):
        captured.update(
            name=name, from_model=from_model, system=system, parameters=parameters
        )
        return {"status": "success"}

    monkeypatch.setattr(ollama_client, "create_model", fake_create)
    r = client.post(
        "/api/models/create",
        json={
            "name": "mine:v1",
            "from_model": "qwen2.5",
            "system": "Be terse.",
            "parameters": {"temperature": 0.1},
        },
    )
    assert r.status_code == 200 and r.json() == {"name": "mine:v1", "status": "success"}
    assert captured["parameters"] == {"temperature": 0.1}
    assert (
        client.post(
            "/api/models/create", json={"name": " ", "from_model": "x"}
        ).status_code
        == 400
    )

    def boom(*a, **k):
        raise RuntimeError("no such base")

    monkeypatch.setattr(ollama_client, "create_model", boom)
    r = client.post(
        "/api/models/create", json={"name": "mine:v1", "from_model": "nope"}
    )
    assert r.status_code == 400 and "no such base" in r.json()["detail"]


def test_vault_routes(client, tmp_path, monkeypatch):
    assert client.get("/api/models/vault").json() == {
        "vault_dir": str(tmp_path / "vault"),
        "entries": [],
    }
    assert (
        client.post(
            "/api/models/vault/export", json={"name": "qwen2.5:latest"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/models/vault/import", json={"name": "qwen2.5:latest"}
        ).status_code
        == 404
    )

    def fake_export(name, details=None, **kw):
        return {
            "name": name,
            "size": 10,
            "blobs": 2,
            "copied_blobs": 2,
            "details": details,
        }

    monkeypatch.setattr(vault, "export_model", fake_export)
    monkeypatch.setattr(
        vault,
        "list_vault",
        lambda vault_dir=None: [
            {
                "name": "qwen2.5:latest",
                "safe_name": "qwen2.5__latest",
                "exported_at": "t",
                "size": 10,
                "blobs": 2,
                "details": {},
            },
            {
                "name": "gone:1b",
                "safe_name": "gone__1b",
                "exported_at": "t",
                "size": 1,
                "blobs": 1,
                "details": {},
            },
        ],
    )
    r = client.post("/api/models/vault/export", json={"name": "qwen2.5:latest"})
    assert r.json() == {
        "name": "qwen2.5:latest",
        "size": 10,
        "blobs": 2,
        "copied_blobs": 2,
    }
    entries = client.get("/api/models/vault").json()["entries"]
    assert [(e["name"], e["installed"]) for e in entries] == [
        ("qwen2.5:latest", True),
        ("gone:1b", False),
    ]

    monkeypatch.setattr(
        vault,
        "import_model",
        lambda name, **kw: {"name": name, "size": 1, "blobs": 1, "copied_blobs": 1},
    )
    assert (
        client.post("/api/models/vault/import", json={"name": "gone:1b"}).json()[
            "copied_blobs"
        ]
        == 1
    )

    deleted = []
    monkeypatch.setattr(
        vault, "delete_from_vault", lambda name, vault_dir=None: deleted.append(name)
    )
    assert client.delete("/api/models/vault/hf.co/org/repo:Q4").status_code == 200
    assert deleted == ["hf.co/org/repo:Q4"]
