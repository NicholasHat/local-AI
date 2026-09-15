"""Model catalog — a curated seed plus live feeds (plan.md decision 6,
Phases 19–26).

catalog.yaml is the checked-in, dated seed of open-weight families worth
holding locally. Currency comes from two optional network calls, both
stdlib urllib with short timeouts and an in-memory cache, and both
returning a structured error instead of raising so the Models page keeps
working offline:

  trending()      — Hugging Face's public trending-GGUF feed. Ollama pulls
                    GGUF straight from Hugging Face as
                    `hf.co/<org>/<repo>[:<quant>]` (e.g. hf.co/unsloth/
                    Qwen3-8B-GGUF:Q4_K_M), so nothing is limited to Ollama's
                    own library.
  check_updates() — for each installed library model, fetch the registry
                    manifest and compare. Verified live 2026-09-15: the
                    `digest` Ollama reports for an installed tag IS the
                    sha256 of its manifest bytes, and the registry serves
                    those exact bytes (no Docker-Content-Digest header), so
                    "update available" == sha256(remote manifest) differs
                    from the local digest.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

import config

CATALOG_PATH = Path(__file__).parent / "catalog.yaml"
HF_TRENDING_URL = "https://huggingface.co/api/models"
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2/library"

_CATEGORIES = {"general", "coding", "reasoning", "vision", "embedding", "small"}
_CAPABILITIES = {"tools", "vision", "reasoning", "embedding"}
_TIMEOUT_SECONDS = 10
_CACHE_TTL_SECONDS = 15 * 60
_USER_AGENT = "local-ai-assistant/1.0"

_cache: dict[str, tuple[float, dict]] = {}


class CatalogError(Exception):
    """Malformed catalog.yaml (the whole file, not one entry)."""


# --- Seed ------------------------------------------------------------------


def _validate_entry(raw: dict) -> dict:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("entry without a name")
    category = raw.get("category")
    if category not in _CATEGORIES:
        raise ValueError(f"{name}: unknown category {category!r}")
    capabilities = list(raw.get("capabilities") or [])
    bad = set(capabilities) - _CAPABILITIES
    if bad:
        raise ValueError(f"{name}: unknown capabilities {sorted(bad)}")
    tags = []
    for t in raw.get("ollama_tags") or []:
        tag = str(t.get("tag") or "").strip() if isinstance(t, dict) else str(t)
        if not tag:
            raise ValueError(f"{name}: ollama_tags entry without a tag")
        size = str(t.get("size") or "") if isinstance(t, dict) else ""
        tags.append({"tag": tag, "size": size})
    if not tags:
        raise ValueError(f"{name}: no ollama_tags")
    return {
        "name": name,
        "org": str(raw.get("org") or ""),
        "family": str(raw.get("family") or ""),
        "category": category,
        "description": str(raw.get("description") or "").strip(),
        "license": str(raw.get("license") or ""),
        "capabilities": capabilities,
        "recommended": bool(raw.get("recommended", False)),
        "ollama_tags": tags,
        "hf_repo": str(raw.get("hf_repo") or ""),
        "notes": str(raw.get("notes") or "").strip(),
    }


def seed() -> dict:
    """The parsed, validated seed: {"updated", "note", "models", "errors"}.
    A bad entry is skipped and reported in `errors`, never fatal."""
    try:
        data = yaml.safe_load(CATALOG_PATH.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"catalog.yaml unreadable: {exc}") from exc
    models, errors = [], []
    for raw in data.get("models") or []:
        try:
            models.append(_validate_entry(raw if isinstance(raw, dict) else {}))
        except ValueError as exc:
            errors.append(str(exc))
    return {
        "updated": str(data.get("updated") or ""),
        "note": str(data.get("note") or "").strip(),
        "models": models,
        "errors": errors,
    }


def library() -> list[dict]:
    """The flat recommended list ModelManager.tsx consumes: one row per
    recommended family by bare name (pulling `qwen2.5` gets Ollama's default
    tag) — {name, description, tool_capable}."""
    return [
        {
            "name": m["name"],
            "description": m["description"],
            "tool_capable": "tools" in m["capabilities"],
        }
        for m in seed()["models"]
        if m["recommended"]
    ]


def _tag_matches(tag: str, installed_names: set[str]) -> bool:
    """`qwen2.5:7b` counts as installed if that exact tag is, and a `:latest`
    tag also matches the bare name (Ollama reports `qwen2.5:latest` for a
    pull of `qwen2.5`)."""
    if tag in installed_names:
        return True
    if tag.endswith(":latest") and tag[: -len(":latest")] in installed_names:
        return True
    return False


def catalog(installed: list[dict]) -> dict:
    """The seed with installation state merged in: each tag gets
    `installed` (exact match, or `:latest` for a bare pull), and each family
    gets `installed_tags` — every installed name whose base matches the
    family (so `qwen2.5:latest` shows under the qwen2.5 family even though
    the seed lists it as `qwen2.5:7b`) — and `installed_any`. `installed` is
    ollama_client.list_models()' shape."""
    names = {m["name"] for m in installed}
    data = seed()
    for model in data["models"]:
        for t in model["ollama_tags"]:
            t["installed"] = _tag_matches(t["tag"], names)
        model["installed_tags"] = sorted(
            n for n in names if n.partition(":")[0] == model["name"]
        )
        model["installed_any"] = bool(model["installed_tags"]) or any(
            t["installed"] for t in model["ollama_tags"]
        )
    return data


# --- Live feeds ----------------------------------------------------------------


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read()


def _cached(key: str, refresh: bool, compute) -> dict:
    now = time.time()
    hit = _cache.get(key)
    if hit and not refresh and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    result = compute()
    if not result.get("error"):
        _cache[key] = (now, result)
    return result


def _error(message: str) -> dict:
    return {"error": message, "offline": True}


def trending(limit: int = 20, refresh: bool = False) -> dict:
    """Trending GGUF repos on Hugging Face, each with a pullable
    `hf.co/<repo>` tag. {"entries": [...], "fetched_at"} or an error dict."""
    limit = max(1, min(int(limit or 20), 50))

    def compute() -> dict:
        url = (
            HF_TRENDING_URL
            + "?"
            + urllib.parse.urlencode(
                {"filter": "gguf", "sort": "trendingScore", "limit": limit}
            )
        )
        try:
            rows = json.loads(_fetch(url).decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return _error(f"Hugging Face unreachable: {exc}")
        entries = []
        for row in rows:
            repo = row.get("id") or row.get("modelId") or ""
            if not repo:
                continue
            tags = row.get("tags") or []
            licenses = [t[len("license:") :] for t in tags if t.startswith("license:")]
            entries.append(
                {
                    "repo": repo,
                    "pull_tag": f"hf.co/{repo}",
                    "likes": row.get("likes") or 0,
                    "downloads": row.get("downloads") or 0,
                    "trending_score": row.get("trendingScore") or 0,
                    "pipeline": row.get("pipeline_tag") or "",
                    "license": licenses[0] if licenses else "",
                    "created_at": row.get("createdAt") or "",
                }
            )
        return {
            "entries": entries,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    return _cached(f"trending:{limit}", refresh, compute)


def _split_library_name(name: str) -> tuple[str, str] | None:
    """`qwen2.5:latest` -> ("qwen2.5", "latest"); None for anything that
    isn't a plain Ollama library name (hf.co/..., user/model, custom builds
    are all outside the library registry)."""
    if "/" in name:
        return None
    base, _, tag = name.partition(":")
    return base, tag or "latest"


def _local_digest(model: dict) -> str | None:
    """The installed manifest digest — from list_models() when the server
    reports it, else by hashing the manifest file on disk."""
    if model.get("digest"):
        return model["digest"]
    split = _split_library_name(model["name"])
    if split is None:
        return None
    path = (
        config.get_ollama_models_dir()
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / split[0]
        / split[1]
    )
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_updates(installed: list[dict], refresh: bool = False) -> dict:
    """For each installed model: {"name", "status": up_to_date | update_available
    | unknown | skipped, "reason"?, "local_digest"?, "remote_digest"?}.
    Wrapped as {"models": [...], "checked_at"} — a fully offline check
    reports every model as `unknown` with the reason, never an exception."""

    def compute() -> dict:
        results = []
        for model in installed:
            name = model["name"]
            split = _split_library_name(name)
            if split is None:
                results.append(
                    {
                        "name": name,
                        "status": "skipped",
                        "reason": "not an Ollama library model",
                    }
                )
                continue
            local = _local_digest(model)
            url = f"{OLLAMA_REGISTRY}/{split[0]}/manifests/{split[1]}"
            try:
                remote = hashlib.sha256(_fetch(url)).hexdigest()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                results.append(
                    {
                        "name": name,
                        "status": "unknown",
                        "reason": f"registry unreachable: {exc}",
                    }
                )
                continue
            if local is None:
                status, reason = "unknown", "no local manifest digest"
            elif local == remote:
                status, reason = "up_to_date", None
            else:
                status, reason = "update_available", None
            entry = {
                "name": name,
                "status": status,
                "local_digest": local,
                "remote_digest": remote,
            }
            if reason:
                entry["reason"] = reason
            results.append(entry)
        return {
            "models": results,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    key = "updates:" + ",".join(sorted(m["name"] for m in installed))
    return _cached(key, refresh, compute)
