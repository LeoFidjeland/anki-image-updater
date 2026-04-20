"""
Optional round-robin pools of API keys for stock providers.

Enable with ``ANKI_IMAGE_UPDATER_USE_KEY_POOLS=1`` in the environment (see
``.env`` in the project directory). Keys are read from a JSON file —
default path: ``api_key_pools.json`` in the same folder as this package's
sources (the repo / app code directory), or override with
``ANKI_IMAGE_UPDATER_KEY_POOL_PATH``.

When pooling is off or the file is missing/invalid, behavior matches the
single-key path via :class:`config_manager.ConfigManager` only.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from config_manager import ConfigManager

logger = logging.getLogger(__name__)

ENV_USE_KEY_POOLS = "ANKI_IMAGE_UPDATER_USE_KEY_POOLS"
ENV_KEY_POOL_PATH = "ANKI_IMAGE_UPDATER_KEY_POOL_PATH"

PROVIDERS = ("pexels", "unsplash", "freepik", "pixabay")

CONFIG_KEY_BY_PROVIDER: dict[str, str] = {
    "pexels": "PEXELS_API_KEY",
    "unsplash": "UNSPLASH_ACCESS_KEY",
    "freepik": "FREEPIK_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
}


def _env_truthy(name: str) -> bool:
    v = os.getenv(name)
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _default_pool_file_path() -> Path:
    """``api_key_pools.json`` next to these modules (project root in a dev clone)."""
    return Path(__file__).resolve().parent / "api_key_pools.json"


def pool_path_for_config(config: ConfigManager) -> Path:
    """Resolve pool file path; ``config`` is kept for API stability (unused for the default)."""
    _ = config
    env_path = os.getenv(ENV_KEY_POOL_PATH)
    if env_path:
        return Path(env_path).expanduser()
    return _default_pool_file_path()


def _normalize_provider_lists(raw: dict[str, Any]) -> dict[str, list[str]]:
    """Keep only known providers; strip strings; drop empties; dedupe order."""
    out: dict[str, list[str]] = {}
    for prov in PROVIDERS:
        vals = raw.get(prov)
        if not isinstance(vals, list):
            continue
        cleaned: list[str] = []
        for x in vals:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                cleaned.append(s)
        if not cleaned:
            continue
        out[prov] = list(dict.fromkeys(cleaned))
    return out


def load_pool_file(path: Path) -> dict[str, list[str]] | None:
    """
    Load and normalize ``api_key_pools.json``.

    Returns ``None`` if the file is missing, unreadable, or not a JSON object.
    An empty object ``{}`` is valid and yields an empty dict (all lookups
    fall back to single-key settings).
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        logger.error("Could not read API key pool file %s: %s", path, e)
        return None
    if not isinstance(raw, dict):
        logger.error("API key pool file %s must contain a JSON object.", path)
        return None
    return _normalize_provider_lists(raw)


class ApiKeyAllocator:
    """Thread-safe round-robin over per-provider key lists."""

    def __init__(self, pools: dict[str, Any]) -> None:
        norm = _normalize_provider_lists(pools) if isinstance(pools, dict) else {}
        self._pools = {p: list(keys) for p, keys in norm.items() if keys}
        self._counters: dict[str, int] = {p: 0 for p in self._pools}
        self._lock = threading.Lock()

    def has_provider(self, provider: str) -> bool:
        """True if this pool has at least one key for ``provider`` (no side effects)."""
        return bool(self._pools.get(provider))

    def next_key(self, provider: str) -> str | None:
        keys = self._pools.get(provider)
        if not keys:
            return None
        with self._lock:
            idx = self._counters[provider]
            self._counters[provider] = (idx + 1) % len(keys)
            key = keys[idx]
            n = len(keys)
        # Lets you confirm round-robin in logs without echoing full secrets (httpx may still log URLs).
        logger.info(
            "API key pool: %s entry %d/%d (round-robin)",
            provider,
            idx + 1,
            n,
        )
        return key


_allocator: ApiKeyAllocator | None = None
_allocator_lock = threading.Lock()
_allocator_configured = False


def reset_allocator() -> None:
    """Test hook — clears cached allocator state."""
    global _allocator, _allocator_configured
    with _allocator_lock:
        _allocator = None
        _allocator_configured = False


def _get_allocator(config: ConfigManager) -> ApiKeyAllocator | None:
    global _allocator, _allocator_configured
    with _allocator_lock:
        if _allocator_configured:
            return _allocator
        _allocator_configured = True
        if not _env_truthy(ENV_USE_KEY_POOLS):
            _allocator = None
            return None
        path = pool_path_for_config(config)
        data = load_pool_file(path)
        if data is None:
            if path.is_file():
                logger.warning(
                    "API key pools are enabled but %s could not be loaded — "
                    "using single-key settings only.",
                    path,
                )
            else:
                logger.warning(
                    "API key pools are enabled but %s does not exist — "
                    "using single-key settings only.",
                    path,
                )
            _allocator = None
            return None
        if not data:
            logger.info(
                "API key pool file %s has no non-empty provider entries — "
                "using single-key settings only.",
                path,
            )
            _allocator = None
            return None
        _allocator = ApiKeyAllocator(data)
        summary = ", ".join(
            f"{p}: {len(data[p])} key(s)" for p in sorted(data.keys())
        )
        logger.info("API key pools loaded from %s — %s", path, summary)
        return _allocator


def resolve_api_key(config: ConfigManager, provider: str) -> str:
    """
    Return the next API key for ``provider`` (one of ``pexels``, ``unsplash``,
    ``freepik``, ``pixabay``), or the single-key value from settings/env.

    Pool takes precedence when enabled *and* that provider has at least one
    key in the pool file; otherwise falls back to ``ConfigManager.get``.
    """
    cfg_key = CONFIG_KEY_BY_PROVIDER.get(provider)
    if not cfg_key:
        return ""

    alloc = _get_allocator(config)
    if alloc is not None:
        pooled = alloc.next_key(provider)
        if pooled:
            return pooled

    val = config.get(cfg_key)
    return (val or "").strip()


def provider_has_credentials(config: ConfigManager, provider: str) -> bool:
    """
    True if a key exists for ``provider`` (pool or single-key settings).

    Does **not** advance the round-robin — safe for UI checks on every page load.
    """
    cfg_key = CONFIG_KEY_BY_PROVIDER.get(provider)
    if not cfg_key:
        return False
    alloc = _get_allocator(config)
    if alloc is not None and alloc.has_provider(provider):
        return True
    return bool((config.get(cfg_key) or "").strip())
