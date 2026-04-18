"""Unit tests for AnkiClient (mocked httpx; no Anki required)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from anki_client import AnkiClient, AnkiConnectError


@pytest.fixture
def anki() -> AnkiClient:
    return AnkiClient(url="http://127.0.0.1:8765")


def _patch_async_client(monkeypatch, mock_client: AsyncMock) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)


@pytest.mark.asyncio
async def test_invoke_returns_result(anki, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"result": {"a": 1}, "error": None})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    _patch_async_client(monkeypatch, mock_client)

    assert await anki.invoke("deckNames") == {"a": 1}
    mock_client.post.assert_awaited_once()
    call_kw = mock_client.post.await_args.kwargs
    assert call_kw["json"]["action"] == "deckNames"
    assert call_kw["json"]["version"] == 6


@pytest.mark.asyncio
async def test_invoke_raises_on_api_error_field(anki, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"result": None, "error": "invalid action"})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    _patch_async_client(monkeypatch, mock_client)

    with pytest.raises(AnkiConnectError, match="invalid action"):
        await anki.invoke("nope")


@pytest.mark.asyncio
async def test_invoke_raises_on_unexpected_json_shape(anki, monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"only_one_key": True})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    _patch_async_client(monkeypatch, mock_client)

    with pytest.raises(AnkiConnectError, match="unexpected number of fields"):
        await anki.invoke("x")


@pytest.mark.asyncio
async def test_fetch_decks_returns_empty_list_on_error(anki, monkeypatch):
    async def fail_invoke(*_a, **_k):
        raise AnkiConnectError("down")

    monkeypatch.setattr(anki, "invoke", fail_invoke)
    assert await anki.fetch_decks() == []
