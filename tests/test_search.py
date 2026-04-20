import asyncio

import image_sizing as iz
import pytest
from unittest.mock import AsyncMock, MagicMock

from search_providers import GRID_THUMB_MAX_DIM, ImageSearcher, _parse_freepik_source_size


@pytest.mark.asyncio
async def test_search_pexels_no_key(mock_config):
    """Test that pexels search raises if no key."""
    mock_config.set("PEXELS_API_KEY", "")

    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Pexels API key is missing."):
        await searcher.search_pexels("test")


@pytest.mark.asyncio
async def test_search_pexels_with_key_mocked(mock_config, mock_httpx):
    """Test pexels search with mocked response."""
    mock_config.set("PEXELS_API_KEY", "fake_key")

    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "photos": [
            {
                "src": {
                    "medium": "medium_url",
                    "large2x": "full_url",
                    "large": "large_url",
                    "original": "orig_url",
                },
                "url": "context_url",
                "width": 4000,
                "height": 3000,
            }
        ]
    }

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_pexels("test")

    assert len(results) == 1
    # Preview: smallest tier with nominal >= GRID long-edge target → large (>=420)
    assert results[0]["thumb"] == "large_url"
    # Save: native long edge > SAVE_MAX_DIM → smallest save tier >= 1920 → large2x
    assert results[0]["full"] == "full_url"
    assert results[0]["provider"] == "Pexels"
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 315


@pytest.mark.asyncio
async def test_search_missing_provider_key(mock_config):
    """Verify other providers raise if key missing."""
    mock_config.set("UNSPLASH_ACCESS_KEY", "")
    mock_config.set("FREEPIK_API_KEY", "")
    mock_config.set("PIXABAY_API_KEY", "")

    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Unsplash API key is missing."):
        await searcher.search_unsplash("test")
    with pytest.raises(ValueError, match="Freepik API key is missing."):
        await searcher.search_freepik("test")
    with pytest.raises(ValueError, match="Pixabay API key is missing."):
        await searcher.search_pixabay("test")


@pytest.mark.asyncio
async def test_make_search_request_401(mock_httpx):
    """Test that make_search_request raises ValueError on 401."""
    mock_client, mock_response = mock_httpx
    mock_response.status_code = 401

    searcher = ImageSearcher(None)
    with pytest.raises(ValueError, match="API key is invalid or unauthorized"):
        await searcher.make_search_request("http://fake.url", headers={})


@pytest.mark.asyncio
async def test_search_unsplash_with_key_mocked(mock_config, mock_httpx):
    """Test unsplash search with mocked response."""
    mock_config.set("UNSPLASH_ACCESS_KEY", "fake_unsplash_key")

    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "results": [
            {
                "urls": {"small": "unsplash_thumb", "raw": "https://images.unsplash.com/raw"},
                "links": {"html": "unsplash_context"},
                "width": 4000,
                "height": 3000,
            }
        ]
    }

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_unsplash("test")

    assert len(results) == 1
    assert "w=420" in results[0]["thumb"]
    assert "w=1920" in results[0]["full"]
    assert results[0]["context_url"] == "unsplash_context"
    assert results[0]["provider"] == "Unsplash"
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 315


@pytest.mark.asyncio
async def test_search_freepik_with_key_mocked(mock_config, mock_httpx):
    """Test freepik search with mocked response."""
    mock_config.set("FREEPIK_API_KEY", "fake_freepik_key")

    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "data": [
            {
                "image": {"source": {"url": "freepik_url", "size": "800x600"}},
                "url": "freepik_context",
            }
        ]
    }

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_freepik("test")

    assert len(results) == 1
    assert results[0]["thumb"] == "freepik_url"
    assert results[0]["full"] == "freepik_url"
    assert results[0]["context_url"] == "freepik_context"
    assert results[0]["provider"] == "Freepik"
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 315


@pytest.mark.asyncio
async def test_search_pixabay_no_key(mock_config):
    """Test that Pixabay search raises if no key."""
    mock_config.set("PIXABAY_API_KEY", "")

    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Pixabay API key is missing."):
        await searcher.search_pixabay("test")


@pytest.mark.asyncio
async def test_search_pixabay_with_key_mocked(mock_config, mock_httpx):
    """Test Pixabay search with mocked response."""
    mock_config.set("PIXABAY_API_KEY", "fake_pixabay_key")

    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "hits": [
            {
                "previewURL": "pix_prev",
                "webformatURL": "https://cdn.pixabay.com/photo/x_y_640.jpg",
                "largeImageURL": "pix_large",
                "fullHDURL": "pix_hd",
                "pageURL": "pix_context",
                "imageWidth": 1200,
                "imageHeight": 800,
            }
        ]
    }

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_pixabay("test", count=1)

    assert len(results) == 1
    assert "_340." in results[0]["thumb"]
    assert results[0]["full"] == "pix_large"
    assert results[0]["context_url"] == "pix_context"
    assert results[0]["provider"] == "Pixabay"
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 280


def test_parse_freepik_source_size():
    assert _parse_freepik_source_size({"source": {"size": "740x640"}}) == (740, 640)
    assert _parse_freepik_source_size({"source": {"size": "740×640"}}) == (740, 640)
    assert _parse_freepik_source_size({"source": {}}) == (None, None)
    assert _parse_freepik_source_size(None) == (None, None)


def test_thumb_dims():
    assert iz.thumb_dims(100, 50) == {"thumb_width": 100, "thumb_height": 50}
    assert iz.thumb_dims(None, 50) == {}
    assert iz.thumb_dims(0, 100) == {}


def test_preview_dims_from_original_scales_down():
    assert iz.preview_dims_from_original(4000, 3000) == {"thumb_width": 420, "thumb_height": 315}
    assert iz.preview_dims_from_original(800, 600) == {"thumb_width": 420, "thumb_height": 315}


def test_unsplash_sized_raw_url_appends_params():
    assert "w=420" in iz.unsplash_sized_raw_url("https://x.com/a", 420)
    assert "w=420" in iz.unsplash_sized_raw_url("https://x.com/a?ix=1", 420)


def test_pixabay_webformat_smaller_replaces_640():
    u = "https://cdn.example.com/a_640.jpg"
    assert "_340." in iz.pixabay_webformat_smaller(u)


def test_smallest_preset_ge():
    assert iz.smallest_preset_ge([100, 200, 300], 199) == 200
    assert iz.smallest_preset_ge([100, 200, 300], 200) == 200
    assert iz.smallest_preset_ge([100, 200, 300], 301) == 300


def test_wikimedia_shrink_existing_thumb_url_rewrites_width():
    u = (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/"
        "Foo_%28bar%29.jpg/2048px-Foo_%28bar%29.jpg"
    )
    out = iz.wikimedia_shrink_existing_thumb_url(u, 420)
    assert "420px-Foo_" in out
    assert "2048px-" not in out


def test_wikimedia_shrink_existing_thumb_url_does_not_upscale():
    u = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Foo.jpg/200px-Foo.jpg"
    assert iz.wikimedia_shrink_existing_thumb_url(u, GRID_THUMB_MAX_DIM) == u


def test_width_param_for_max_long_edge_portrait_and_landscape():
    assert iz.width_param_for_max_long_edge(1610, 2478, 420) == 273
    assert iz.width_param_for_max_long_edge(8256, 5504, 1920) == 1920
    assert iz.width_param_for_max_long_edge(200, 200, 420) is None


def test_commons_thumb_url_from_original():
    orig = "https://upload.wikimedia.org/wikipedia/commons/e/ef/Senador_Tancredo_Neves.jpg"
    u = iz.commons_thumb_url_from_original(orig, 312)
    assert "/commons/thumb/e/ef/" in u
    assert "312px-Senador_Tancredo_Neves.jpg" in u


@pytest.mark.asyncio
async def test_search_wikimedia_uses_api_thumbs_for_grid_and_save(mock_config, mock_httpx):
    """Grid ``thumb`` from search ``iiurlwidth``; ``full`` from a second batched ``imageinfo`` query."""
    mock_client, _ = mock_httpx
    search_json = {
        "query": {
            "pages": {
                "85062281": {
                    "index": 1,
                    "title": "File:Senador Tancredo Neves.jpg",
                    "imageinfo": [
                        {
                            "mime": "image/jpeg",
                            "url": "https://upload.wikimedia.org/wikipedia/commons/e/ef/Senador_Tancredo_Neves.jpg",
                            "width": 1610,
                            "height": 2478,
                            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Senador_Tancredo_Neves.jpg/420px-Senador_Tancredo_Neves.jpg",
                            "thumbwidth": 420,
                            "thumbheight": 647,
                        }
                    ],
                }
            }
        }
    }
    batch_json = {
        "query": {
            "pages": {
                "85062281": {
                    "title": "File:Senador Tancredo Neves.jpg",
                    "imageinfo": [
                        {
                            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Senador_Tancredo_Neves.jpg/1247px-Senador_Tancredo_Neves.jpg",
                            "url": "https://upload.wikimedia.org/wikipedia/commons/e/ef/Senador_Tancredo_Neves.jpg",
                        }
                    ],
                }
            }
        }
    }
    resp_search = MagicMock()
    resp_search.status_code = 200
    resp_search.raise_for_status = MagicMock()
    resp_search.json.return_value = search_json
    resp_batch = MagicMock()
    resp_batch.status_code = 200
    resp_batch.raise_for_status = MagicMock()
    resp_batch.json.return_value = batch_json
    mock_client.get = AsyncMock(side_effect=[resp_search, resp_batch])

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_wikimedia("senador", count=1)
    assert len(results) == 1
    assert results[0]["thumb"] != results[0]["full"]
    assert "/commons/thumb/" in results[0]["thumb"]
    assert "420px-" in results[0]["thumb"]
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 647
    assert results[0]["full"] == batch_json["query"]["pages"]["85062281"]["imageinfo"][0]["thumburl"]
    assert "upload.wikimedia.org/wikipedia/commons/e/ef/Senador" not in results[0]["thumb"]


@pytest.mark.asyncio
async def test_search_wikimedia_svg_uses_original_no_batch(mock_config, mock_httpx):
    """SVG uses the Commons file URL for grid + save; no second imageinfo batch."""
    mock_client, mock_response = mock_httpx
    svg_url = "https://upload.wikimedia.org/wikipedia/commons/3/3f/Example.svg"
    search_json = {
        "query": {
            "pages": {
                "1": {
                    "index": 1,
                    "title": "File:Example.svg",
                    "imageinfo": [
                        {
                            "mime": "image/svg+xml",
                            "url": svg_url,
                            "size": 123,
                            "width": 600,
                            "height": 400,
                        }
                    ],
                }
            }
        }
    }
    mock_response.json.return_value = search_json
    mock_client.get = AsyncMock(return_value=mock_response)

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_wikimedia("example", count=1)
    assert len(results) == 1
    assert results[0]["thumb"] == svg_url
    assert results[0]["full"] == svg_url
    assert results[0]["media_ext"] == "svg"
    assert results[0]["thumb_width"] == 420
    assert results[0]["thumb_height"] == 280
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_wikimedia_svg_fallback_aspect_when_no_api_dims(
    mock_config, mock_httpx
):
    """SVG without width/height from API uses 4:3 grid cell (matches UI default)."""
    mock_client, mock_response = mock_httpx
    svg_url = "https://upload.wikimedia.org/wikipedia/commons/x/x/Foo.svg"
    mock_response.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "index": 1,
                    "title": "File:Foo.svg",
                    "imageinfo": [
                        {"mime": "image/svg+xml", "url": svg_url, "size": 1}
                    ],
                }
            }
        }
    }
    mock_client.get = AsyncMock(return_value=mock_response)
    results = await ImageSearcher(mock_config).search_wikimedia("x", count=1)
    assert results[0]["thumb_width"] == GRID_THUMB_MAX_DIM
    assert results[0]["thumb_height"] == int(round(GRID_THUMB_MAX_DIM * 3 / 4))


def test_pexels_thumb_full_urls_respects_save_max(monkeypatch):
    src = {"large": "L", "large2x": "L2", "original": "O"}
    ow, oh = 2000, 1500
    monkeypatch.setattr(iz, "SAVE_MAX_DIM", 1280)
    _, full = iz.pexels_thumb_full_urls(src, ow, oh)
    assert full == "L"
    monkeypatch.setattr(iz, "SAVE_MAX_DIM", 1920)
    _, full = iz.pexels_thumb_full_urls(src, ow, oh)
    assert full == "L2"
    monkeypatch.setattr(iz, "SAVE_MAX_DIM", 3000)
    _, full = iz.pexels_thumb_full_urls(src, 4000, 3000)
    assert full == "O"


@pytest.mark.asyncio
async def test_search_cache_reuses_results(mock_config, mock_httpx):
    """search() hits the in-memory cache; clear_search_cache forces a new HTTP call."""
    mock_config.set("PEXELS_API_KEY", "fake_key")
    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "photos": [
            {
                "src": {"medium": "thumb_u", "large": "large_u", "large2x": "full_u"},
                "url": "ctx",
                "width": 1200,
                "height": 800,
            }
        ]
    }
    searcher = ImageSearcher(mock_config)
    r1 = await searcher.search("pexels", "dog", count=6, page=1)
    r2 = await searcher.search("pexels", "dog", count=6, page=1)
    assert mock_client.get.call_count == 1
    assert r1 == r2

    await searcher.search("pexels", "  Dog  ", count=6, page=1)
    assert mock_client.get.call_count == 1

    await searcher.search("pexels", "dog", count=6, page=2)
    assert mock_client.get.call_count == 2

    searcher.clear_search_cache()
    await searcher.search("pexels", "dog", count=6, page=1)
    assert mock_client.get.call_count == 3


@pytest.mark.asyncio
async def test_search_inflight_dedupes_concurrent_calls(mock_config, mock_httpx):
    """Two overlapping search() calls for the same key share one HTTP request."""
    mock_config.set("PEXELS_API_KEY", "fake_key")
    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "photos": [
            {
                "src": {"medium": "u", "large": "lu", "large2x": "f"},
                "url": "ctx",
                "width": 1200,
                "height": 800,
            }
        ]
    }
    searcher = ImageSearcher(mock_config)
    await asyncio.gather(
        searcher.search("pexels", "overlap", count=6, page=1),
        searcher.search("pexels", "overlap", count=6, page=1),
    )
    assert mock_client.get.call_count == 1
