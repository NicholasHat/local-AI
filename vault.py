"""The vault — the actual insurance policy (plan.md decision 7, Phases
19–26).

Ollama stores an installed model as a manifest at
    <models_dir>/manifests/<host>/<namespace>/<name>/<tag>
whose `config.digest` and `layers[].digest` name content-addressed blobs at
    <models_dir>/blobs/sha256-<hex>
(verified on disk 2026-09-15). Everything a model *is* lives in those
files, so archiving a model = copying its manifest and every referenced
blob into a plain directory — an external drive, a NAS — with no registry
involved. Restoring = copying them back. A vaulted model survives its
upstream being pulled, relicensed, or paywalled.

Vault layout, one directory per model under config.get_vault_dir():
    <vault>/<safe-name>/meta.json      name, exported_at, size, details
    <vault>/<safe-name>/manifest.json  the manifest bytes, unchanged
    <vault>/<safe-name>/blobs/sha256-<hex>

Name resolution mirrors Ollama's: `qwen2.5` -> registry.ollama.ai/library/
qwen2.5/latest; `user/model:tag` -> registry.ollama.ai/user/model/tag;
`hf.co/org/repo:Q4_K_M` -> hf.co/org/repo/Q4_K_M.

Verified live 2026-09-15: after import_model() copies files back, the
running Ollama server lists and chats with the model immediately — it reads
the manifests directory on each request, no restart needed.
"""

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import config

_DEFAULT_HOST = "registry.ollama.ai"
_DEFAULT_NAMESPACE = "library"
_DEFAULT_TAG = "latest"


class VaultError(Exception):
    """Model not installed / not vaulted, or a corrupt vault entry."""


@dataclass(frozen=True)
class ModelRef:
    host: str
    namespace: str
    name: str
    tag: str

    @property
    def display(self) -> str:
        """The name as `ollama list` shows it (no default host/namespace)."""
        prefix = f"{self.host}/" if self.host != _DEFAULT_HOST else ""
        ns = f"{self.namespace}/" if self.namespace != _DEFAULT_NAMESPACE else ""
        return f"{prefix}{ns}{self.name}:{self.tag}"

    @property
    def safe_name(self) -> str:
        """Filesystem-safe directory name: `hf.co/org/repo:Q4` ->
        `hf.co__org__repo__Q4`; `qwen2.5:latest` -> `qwen2.5__latest`."""
        return self.display.replace("/", "__").replace(":", "__")

    def manifest_path(self, models_dir: Path) -> Path:
        return (
            models_dir / "manifests" / self.host / self.namespace / self.name / self.tag
        )


def parse_ref(name: str) -> ModelRef:
    """Split a model name the way Ollama does (module docstring)."""
    name = (name or "").strip()
    if not name or any(c in name for c in " \t\n") or ".." in name:
        raise VaultError(f"Invalid model name: {name!r}")
    base, _, tag = name.partition(":")
    parts = base.split("/")
    if len(parts) == 1:
        host, namespace, model = _DEFAULT_HOST, _DEFAULT_NAMESPACE, parts[0]
    elif len(parts) == 2:
        host, namespace, model = _DEFAULT_HOST, parts[0], parts[1]
    elif len(parts) == 3:
        host, namespace, model = parts
    else:
        raise VaultError(f"Invalid model name: {name!r}")
    if not model or not namespace or not host:
        raise VaultError(f"Invalid model name: {name!r}")
    return ModelRef(host=host, namespace=namespace, name=model, tag=tag or _DEFAULT_TAG)


def _blob_digests(manifest: dict) -> list[str]:
    digests = [manifest["config"]["digest"]]
    digests += [layer["digest"] for layer in manifest.get("layers", [])]
    return digests


def _blob_filename(digest: str) -> str:
    """`sha256:abc...` -> `sha256-abc...` (Ollama's on-disk naming)."""
    return digest.replace(":", "-", 1)


def _copy_if_needed(src: Path, dest: Path) -> bool:
    """Copy unless dest already exists with the same size (content-addressed,
    so same name + same size is the same blob). Returns True if copied."""
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def export_model(
    name: str,
    vault_dir: Path | None = None,
    models_dir: Path | None = None,
    details: dict | None = None,
) -> dict:
    """Archive an installed model into the vault. `details` (show_model's
    dict, supplied by the API layer so this module never talks to Ollama)
    is stored in meta.json for display. Returns the meta record."""
    vault_dir = vault_dir or config.get_vault_dir()
    models_dir = models_dir or config.get_ollama_models_dir()
    ref = parse_ref(name)
    manifest_path = ref.manifest_path(models_dir)
    if not manifest_path.exists():
        raise VaultError(f"{ref.display!r} is not installed (no manifest).")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)

    entry_dir = vault_dir / ref.safe_name
    (entry_dir / "blobs").mkdir(parents=True, exist_ok=True)
    total, copied = 0, 0
    for digest in _blob_digests(manifest):
        src = models_dir / "blobs" / _blob_filename(digest)
        if not src.exists():
            raise VaultError(f"Blob {digest} for {ref.display!r} is missing on disk.")
        if _copy_if_needed(src, entry_dir / "blobs" / _blob_filename(digest)):
            copied += 1
        total += src.stat().st_size
    (entry_dir / "manifest.json").write_bytes(manifest_bytes)
    meta = {
        "name": ref.display,
        "safe_name": ref.safe_name,
        "exported_at": _now(),
        "size": total,
        "blobs": len(_blob_digests(manifest)),
        "details": details or {},
    }
    (entry_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    meta["copied_blobs"] = copied
    return meta


def _entry_dir(name: str, vault_dir: Path) -> Path:
    entry_dir = vault_dir / parse_ref(name).safe_name
    if (
        not (entry_dir / "meta.json").exists()
        or not (entry_dir / "manifest.json").exists()
    ):
        raise VaultError(f"{name!r} is not in the vault.")
    return entry_dir


def import_model(
    name: str, vault_dir: Path | None = None, models_dir: Path | None = None
) -> dict:
    """Restore a vaulted model into Ollama's store. Blobs already present
    (same name + size) are left alone. Returns the meta record."""
    vault_dir = vault_dir or config.get_vault_dir()
    models_dir = models_dir or config.get_ollama_models_dir()
    ref = parse_ref(name)
    entry_dir = _entry_dir(name, vault_dir)
    manifest_bytes = (entry_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)

    copied = 0
    for digest in _blob_digests(manifest):
        src = entry_dir / "blobs" / _blob_filename(digest)
        if not src.exists():
            raise VaultError(
                f"Vault entry for {ref.display!r} is missing blob {digest}."
            )
        if _copy_if_needed(src, models_dir / "blobs" / _blob_filename(digest)):
            copied += 1
    manifest_path = ref.manifest_path(models_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    meta = json.loads((entry_dir / "meta.json").read_text())
    meta["copied_blobs"] = copied
    return meta


def list_vault(vault_dir: Path | None = None) -> list[dict]:
    """Every vaulted model's meta record, newest export first. A directory
    without a readable meta.json is reported with an `error` rather than
    hiding it."""
    vault_dir = vault_dir or config.get_vault_dir()
    if not vault_dir.exists():
        return []
    entries = []
    for entry_dir in sorted(p for p in vault_dir.iterdir() if p.is_dir()):
        meta_path = entry_dir / "meta.json"
        try:
            meta = json.loads(meta_path.read_text())
            meta["safe_name"] = entry_dir.name
        except (OSError, ValueError) as exc:
            meta = {
                "name": entry_dir.name,
                "safe_name": entry_dir.name,
                "error": f"unreadable meta.json: {exc}",
            }
        entries.append(meta)
    entries.sort(key=lambda m: m.get("exported_at", ""), reverse=True)
    return entries


def delete_from_vault(name: str, vault_dir: Path | None = None) -> None:
    vault_dir = vault_dir or config.get_vault_dir()
    shutil.rmtree(_entry_dir(name, vault_dir))
