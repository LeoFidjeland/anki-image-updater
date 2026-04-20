"""Tests for optional multi-key API pools (round-robin, .env switch, JSON file)."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import api_key_pool


def test_allocator_round_robin_per_provider():
    a = api_key_pool.ApiKeyAllocator(
        {"pexels": ["p1", "p2", "p3"], "unsplash": ["u1", "u2"]}
    )
    assert [a.next_key("pexels") for _ in range(6)] == [
        "p1", "p2", "p3", "p1", "p2", "p3",
    ]
    assert [a.next_key("unsplash") for _ in range(4)] == ["u1", "u2", "u1", "u2"]


def test_allocator_unknown_provider_returns_none():
    a = api_key_pool.ApiKeyAllocator({"pexels": ["a"]})
    assert a.next_key("pixabay") is None


def test_allocator_normalizes_json_strips_and_drops_blanks():
    a = api_key_pool.ApiKeyAllocator(
        {"pexels": ["  x  ", "", "  ", "y"], "unsplash": []}
    )
    assert a.next_key("pexels") == "x"
    assert a.next_key("pexels") == "y"
    assert a.next_key("unsplash") is None


def test_load_pool_file_parses_valid_json(tmp_path):
    p = tmp_path / "pools.json"
    p.write_text(
        json.dumps(
            {
                "pexels": ["a", "b"],
                "unsplash": ["x"],
                "freepik": [],
                "pixabay": ["q"],
            }
        ),
        encoding="utf-8",
    )
    data = api_key_pool.load_pool_file(p)
    assert data == {"pexels": ["a", "b"], "unsplash": ["x"], "pixabay": ["q"]}


def test_load_pool_file_missing_returns_none(tmp_path):
    assert api_key_pool.load_pool_file(tmp_path / "nope.json") is None


def test_load_pool_file_invalid_json_returns_none(tmp_path, caplog):
    import logging

    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert api_key_pool.load_pool_file(p) is None
    assert "api key pool" in caplog.text.lower() or "json" in caplog.text.lower()


def test_resolve_api_key_pool_mode_round_robin(monkeypatch, mock_config, tmp_path):
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    pool_path = tmp_path / "api_key_pools.json"
    pool_path.write_text(
        json.dumps({"pexels": ["pool_a", "pool_b"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(pool_path))

    mock_config.set("PEXELS_API_KEY", "from_settings")

    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "pool_a"
    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "pool_b"
    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "pool_a"


def test_resolve_api_key_pool_empty_provider_falls_back_to_config(monkeypatch, mock_config, tmp_path):
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    pool_path = tmp_path / "api_key_pools.json"
    pool_path.write_text(json.dumps({"pexels": ["only"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(pool_path))

    mock_config.set("UNSPLASH_ACCESS_KEY", "fallback_unsplash")

    assert api_key_pool.resolve_api_key(mock_config, "unsplash") == "fallback_unsplash"


def test_resolve_api_key_switch_off_ignores_pool_file(monkeypatch, mock_config, tmp_path):
    monkeypatch.delenv(api_key_pool.ENV_USE_KEY_POOLS, raising=False)
    pool_path = tmp_path / "api_key_pools.json"
    pool_path.write_text(json.dumps({"pexels": ["pool_only"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(pool_path))

    mock_config.set("PEXELS_API_KEY", "settings_key")

    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "settings_key"


def test_default_pool_path_beside_sources(monkeypatch, mock_config, tmp_path):
    """With USE_KEY_POOLS set but no KEY_POOL_PATH, read the default file path
    (normally ``api_key_pools.json`` in the code directory)."""
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "true")
    monkeypatch.delenv(api_key_pool.ENV_KEY_POOL_PATH, raising=False)

    pool_file = tmp_path / "api_key_pools.json"
    pool_file.write_text(
        json.dumps({"pexels": ["from_code_dir"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_key_pool, "_default_pool_file_path", lambda: pool_file)
    mock_config.set("PEXELS_API_KEY", "")

    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "from_code_dir"


def test_resolve_when_pool_file_missing_falls_back(monkeypatch, mock_config, tmp_path):
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(tmp_path / "missing.json"))
    mock_config.set("PEXELS_API_KEY", "solo")

    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "solo"


def test_provider_has_credentials_does_not_advance_round_robin(
    monkeypatch, mock_config, tmp_path
):
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"pexels": ["first", "second"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(p))
    mock_config.set("PEXELS_API_KEY", "")

    assert api_key_pool.provider_has_credentials(mock_config, "pexels")
    assert api_key_pool.provider_has_credentials(mock_config, "pexels")
    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "first"
    assert api_key_pool.resolve_api_key(mock_config, "pexels") == "second"


def test_provider_has_credentials_true_when_pool_only(monkeypatch, mock_config, tmp_path):
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"freepik": ["fk"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(p))
    mock_config.set("FREEPIK_API_KEY", "")

    assert api_key_pool.provider_has_credentials(mock_config, "freepik")


def test_deduplicate_keys_preserves_order():
    a = api_key_pool.ApiKeyAllocator({"pexels": ["a", "a", "b", "a"]})
    assert [a.next_key("pexels") for _ in range(4)] == ["a", "b", "a", "b"]


@pytest.mark.asyncio
async def test_concurrent_round_robin_no_race_errors(monkeypatch, mock_config, tmp_path):
    import asyncio

    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    pool_path = tmp_path / "p.json"
    pool_path.write_text(json.dumps({"pexels": ["x", "y"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(pool_path))
    mock_config.set("PEXELS_API_KEY", "")

    async def grab():
        return api_key_pool.resolve_api_key(mock_config, "pexels")

    out = await asyncio.gather(*[grab() for _ in range(100)])
    assert all(k in ("x", "y") for k in out)
    assert out.count("x") == 50
    assert out.count("y") == 50


@pytest.mark.asyncio
async def test_search_pexels_uses_pool_when_enabled(
    mock_config, mock_httpx, monkeypatch, tmp_path
):
    """Integration: ImageSearcher picks keys from the pool."""
    monkeypatch.setenv(api_key_pool.ENV_USE_KEY_POOLS, "1")
    pool_path = tmp_path / "p.json"
    pool_path.write_text(json.dumps({"pexels": ["k1", "k2"]}), encoding="utf-8")
    monkeypatch.setenv(api_key_pool.ENV_KEY_POOL_PATH, str(pool_path))
    mock_config.set("PEXELS_API_KEY", "ignored_when_pool")

    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {"photos": []}

    from search_providers import ImageSearcher

    searcher = ImageSearcher(mock_config)
    await searcher.search_pexels("q")
    await searcher.search_pexels("q2")

    calls = [c.kwargs.get("headers") or c.args[1] for c in mock_client.get.call_args_list]
    auth_headers = [h.get("Authorization") for h in calls if isinstance(h, dict)]
    assert auth_headers[0] == "k1"
    assert auth_headers[1] == "k2"
