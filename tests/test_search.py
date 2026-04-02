import pytest
from unittest.mock import AsyncMock, MagicMock
from search_providers import ImageSearcher

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
                "url": "context_url"
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = await searcher.search_pexels("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "thumb_url"
    assert results[0]["provider"] == "Pexels"

@pytest.mark.asyncio
async def test_search_missing_provider_key(mock_config):
    """Verify other providers raise if key missing."""
    mock_config.set("UNSPLASH_ACCESS_KEY", "")
    mock_config.set("FREEPIK_API_KEY", "")
    
    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Unsplash API key is missing."):
        await searcher.search_unsplash("test")
    with pytest.raises(ValueError, match="Freepik API key is missing."):
        await searcher.search_freepik("test")

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
                "links": {"html": "unsplash_context"}
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

@pytest.mark.asyncio
async def test_search_freepik_with_key_mocked(mock_config, mock_httpx):
    """Test freepik search with mocked response."""
    mock_config.set("FREEPIK_API_KEY", "fake_freepik_key")
    
    mock_client, mock_response = mock_httpx
    mock_response.json.return_value = {
        "data": [
            {
                "image": {"source": {"url": "freepik_url"}},
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
