import pytest
from unittest.mock import AsyncMock, MagicMock
from search_providers import ImageSearcher, _parse_freepik_source_size, _thumb_dims

@pytest.fixture
def mock_httpx(monkeypatch):
    """Fixture to mock httpx.AsyncClient for search tests."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={})
    
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)
    return mock_client, mock_response

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
                "src": {"medium": "thumb_url", "original": "full_url"},
                "url": "context_url",
                "width": 1200,
                "height": 800,
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = await searcher.search_pexels("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "thumb_url"
    assert results[0]["provider"] == "Pexels"
    assert results[0]["thumb_width"] == 1200
    assert results[0]["thumb_height"] == 800

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
                "urls": {"small": "unsplash_thumb", "raw": "unsplash_full"},
                "links": {"html": "unsplash_context"},
                "width": 4000,
                "height": 3000,
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = await searcher.search_unsplash("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "unsplash_thumb"
    assert results[0]["full"] == "unsplash_full"
    assert results[0]["context_url"] == "unsplash_context"
    assert results[0]["provider"] == "Unsplash"
    assert results[0]["thumb_width"] == 4000
    assert results[0]["thumb_height"] == 3000

@pytest.mark.asyncio
async def test_search_freepik_with_key_mocked(mock_config, mock_httpx):
    """Test freepik search with mocked response."""
    mock_config.set("FREEPIK_API_KEY", "fake_freepik_key")
    
    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "data": [
            {
                "image": {"source": {"url": "freepik_url", "size": "800x600"}},
                "url": "freepik_context"
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
    assert results[0]["thumb_width"] == 800
    assert results[0]["thumb_height"] == 600

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
                "previewURL": "pix_thumb",
                "largeImageURL": "pix_full",
                "pageURL": "pix_context",
                "previewWidth": 150,
                "previewHeight": 99,
            }
        ]
    }

    searcher = ImageSearcher(mock_config)
    results = await searcher.search_pixabay("test", count=1)

    assert len(results) == 1
    assert results[0]["thumb"] == "pix_thumb"
    assert results[0]["full"] == "pix_full"
    assert results[0]["context_url"] == "pix_context"
    assert results[0]["provider"] == "Pixabay"
    assert results[0]["thumb_width"] == 150
    assert results[0]["thumb_height"] == 99


def test_parse_freepik_source_size():
    assert _parse_freepik_source_size({"source": {"size": "740x640"}}) == (740, 640)
    assert _parse_freepik_source_size({"source": {"size": "740×640"}}) == (740, 640)
    assert _parse_freepik_source_size({"source": {}}) == (None, None)
    assert _parse_freepik_source_size(None) == (None, None)


def test_thumb_dims():
    assert _thumb_dims(100, 50) == {"thumb_width": 100, "thumb_height": 50}
    assert _thumb_dims(None, 50) == {}
    assert _thumb_dims(0, 100) == {}
