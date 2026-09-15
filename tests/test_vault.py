"""vault.py against a fake Ollama models dir built in tmp_path — real
file copies, byte-for-byte assertions, no Ollama."""

import hashlib
import json

import pytest

import vault


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def models_dir(tmp_path):
    """A models dir holding `demo:1b` (2 layers + config) and a stray blob."""
    root = tmp_path / "models"
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    config_bytes, layer_a, layer_b = b'{"cfg":1}', b"A" * 1000, b"B" * 20
    layers = []
    for data, media in (
        (layer_a, "application/vnd.ollama.image.model"),
        (layer_b, "application/vnd.ollama.image.system"),
    ):
        (blobs / _digest(data).replace(":", "-")).write_bytes(data)
        layers.append({"mediaType": media, "digest": _digest(data), "size": len(data)})
    (blobs / _digest(config_bytes).replace(":", "-")).write_bytes(config_bytes)
    (blobs / "sha256-deadbeef").write_bytes(b"unrelated")
    manifest = {
        "schemaVersion": 2,
        "config": {"digest": _digest(config_bytes), "size": len(config_bytes)},
        "layers": layers,
    }
    path = root / "manifests" / "registry.ollama.ai" / "library" / "demo" / "1b"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest))
    return root


def test_parse_ref_mirrors_ollama_naming():
    assert vault.parse_ref("qwen2.5").display == "qwen2.5:latest"
    assert vault.parse_ref("qwen2.5:7b").manifest_path(vault.Path("/m")) == vault.Path(
        "/m/manifests/registry.ollama.ai/library/qwen2.5/7b"
    )
    assert vault.parse_ref("user/model:tag").manifest_path(
        vault.Path("/m")
    ) == vault.Path("/m/manifests/registry.ollama.ai/user/model/tag")
    hf = vault.parse_ref("hf.co/org/repo:Q4_K_M")
    assert hf.manifest_path(vault.Path("/m")) == vault.Path(
        "/m/manifests/hf.co/org/repo/Q4_K_M"
    )
    assert hf.display == "hf.co/org/repo:Q4_K_M"
    assert hf.safe_name == "hf.co__org__repo__Q4_K_M"
    for bad in ("", "a/b/c/d", "../x", "a b"):
        with pytest.raises(vault.VaultError):
            vault.parse_ref(bad)


def test_export_copies_manifest_and_only_referenced_blobs(models_dir, tmp_path):
    vault_dir = tmp_path / "vault"
    meta = vault.export_model(
        "demo:1b",
        vault_dir=vault_dir,
        models_dir=models_dir,
        details={"family": "demo"},
    )
    entry = vault_dir / "demo__1b"
    assert meta["copied_blobs"] == 3 and meta["blobs"] == 3
    assert meta["size"] == 1000 + 20 + len(b'{"cfg":1}')
    assert (entry / "manifest.json").read_bytes() == (
        models_dir / "manifests" / "registry.ollama.ai" / "library" / "demo" / "1b"
    ).read_bytes()
    copied = sorted(p.name for p in (entry / "blobs").iterdir())
    assert len(copied) == 3 and "sha256-deadbeef" not in copied
    for blob in (entry / "blobs").iterdir():
        assert blob.read_bytes() == (models_dir / "blobs" / blob.name).read_bytes()
    stored = json.loads((entry / "meta.json").read_text())
    assert stored["name"] == "demo:1b" and stored["details"] == {"family": "demo"}
    # second export skips blobs already present
    assert (
        vault.export_model("demo:1b", vault_dir=vault_dir, models_dir=models_dir)[
            "copied_blobs"
        ]
        == 0
    )


def test_export_not_installed_or_missing_blob(models_dir, tmp_path):
    with pytest.raises(vault.VaultError, match="not installed"):
        vault.export_model("nope:1b", vault_dir=tmp_path / "v", models_dir=models_dir)
    (
        models_dir / "blobs" / ("sha256-" + hashlib.sha256(b"B" * 20).hexdigest())
    ).unlink()
    with pytest.raises(vault.VaultError, match="missing on disk"):
        vault.export_model("demo:1b", vault_dir=tmp_path / "v", models_dir=models_dir)


def test_round_trip_restores_byte_for_byte(models_dir, tmp_path):
    vault_dir = tmp_path / "vault"
    vault.export_model("demo:1b", vault_dir=vault_dir, models_dir=models_dir)
    original = {p.name: p.read_bytes() for p in (models_dir / "blobs").iterdir()}
    manifest_path = (
        models_dir / "manifests" / "registry.ollama.ai" / "library" / "demo" / "1b"
    )
    manifest_bytes = manifest_path.read_bytes()

    restored_dir = tmp_path / "fresh-models"
    meta = vault.import_model("demo:1b", vault_dir=vault_dir, models_dir=restored_dir)
    assert meta["copied_blobs"] == 3
    restored_manifest = (
        restored_dir / "manifests" / "registry.ollama.ai" / "library" / "demo" / "1b"
    )
    assert restored_manifest.read_bytes() == manifest_bytes
    for name, data in original.items():
        if name == "sha256-deadbeef":
            assert not (restored_dir / "blobs" / name).exists()
        else:
            assert (restored_dir / "blobs" / name).read_bytes() == data
    # importing again over an intact store copies nothing
    assert (
        vault.import_model("demo:1b", vault_dir=vault_dir, models_dir=restored_dir)[
            "copied_blobs"
        ]
        == 0
    )


def test_import_missing_entry_or_blob(models_dir, tmp_path):
    vault_dir = tmp_path / "vault"
    with pytest.raises(vault.VaultError, match="not in the vault"):
        vault.import_model("demo:1b", vault_dir=vault_dir, models_dir=models_dir)
    vault.export_model("demo:1b", vault_dir=vault_dir, models_dir=models_dir)
    next((vault_dir / "demo__1b" / "blobs").iterdir()).unlink()
    with pytest.raises(vault.VaultError, match="missing blob"):
        vault.import_model("demo:1b", vault_dir=vault_dir, models_dir=tmp_path / "x")


def test_list_and_delete(models_dir, tmp_path):
    vault_dir = tmp_path / "vault"
    assert vault.list_vault(vault_dir) == []
    vault.export_model("demo:1b", vault_dir=vault_dir, models_dir=models_dir)
    (vault_dir / "broken").mkdir()
    entries = vault.list_vault(vault_dir)
    assert [e["name"] for e in entries] == ["demo:1b", "broken"]
    assert "error" in entries[1]
    vault.delete_from_vault("demo:1b", vault_dir=vault_dir)
    assert not (vault_dir / "demo__1b").exists()
    with pytest.raises(vault.VaultError):
        vault.delete_from_vault("demo:1b", vault_dir=vault_dir)
