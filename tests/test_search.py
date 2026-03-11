import pytest
from search_providers import ImageSearcher
# we import module to patch config inside it if needed, 
# but image_updater imports config instance. We need to patch that instance.

def test_search_pexels_no_key(mock_config):
    """Test that pexels search returns empty list if no key."""
    # Ensure key is empty
    mock_config.set("PEXELS_API_KEY", "")
    
    # Actually testing the searcher instance now
    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Pexels API key is missing."):
        searcher.search_pexels("test")

def test_search_pexels_with_key_mocked(mock_config, mock_requests_get):
    """Test pexels search with mocked response."""
    mock_config.set("PEXELS_API_KEY", "fake_key")
    
    # Mock response
    mock_response = mock_requests_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "photos": [
            {
                "src": {"medium": "thumb_url", "original": "full_url"},
                "url": "context_url"
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = searcher.search_pexels("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "thumb_url"
    assert results[0]["provider"] == "pexels"
    
    # Verify headers contained key
    call_args = mock_requests_get.call_args
    assert call_args[1]['headers']['Authorization'] == "fake_key"

def test_search_missing_provider_key(mock_config):
    """Verify other providers return empty if key missing."""
    mock_config.set("UNSPLASH_ACCESS_KEY", "")
    mock_config.set("FREEPIK_API_KEY", "")
    
    searcher = ImageSearcher(mock_config)
    with pytest.raises(ValueError, match="Unsplash API key is missing."):
        searcher.search_unsplash("test")
    with pytest.raises(ValueError, match="Freepik API key is missing."):
        searcher.search_freepik("test")

def test_make_search_request_401(mock_requests_get):
    """Test that make_search_request raises ValueError on 401."""
    from search_providers import ImageSearcher
    
    mock_response = mock_requests_get.return_value
    mock_response.status_code = 401
    
    searcher = ImageSearcher(None) # Config not needed for this test
    with pytest.raises(ValueError, match="API key is invalid or unauthorized"):
        searcher.make_search_request("http://fake.url", headers={})

def test_search_unsplash_with_key_mocked(mock_config, mock_requests_get):
    """Test unsplash search with mocked response."""
    mock_config.set("UNSPLASH_ACCESS_KEY", "fake_unsplash_key")
    
    # Mock response
    mock_response = mock_requests_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "results": [
            {
                "urls": {"small": "unsplash_thumb", "raw": "unsplash_full"},
                "links": {"html": "unsplash_context"}
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = searcher.search_unsplash("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "unsplash_thumb"
    assert results[0]["full"] == "unsplash_full"
    assert results[0]["context_url"] == "unsplash_context"
    assert results[0]["provider"] == "unsplash"
        
    # Verify headers contained key
    call_args = mock_requests_get.call_args
    assert call_args[1]['headers']['Authorization'] == "Client-ID fake_unsplash_key"

def test_search_freepik_with_key_mocked(mock_config, mock_requests_get):
    """Test freepik search with mocked response."""
    mock_config.set("FREEPIK_API_KEY", "fake_freepik_key")
    
    # Mock response
    mock_response = mock_requests_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "data": [
            {
                "image": {"source": {"url": "freepik_url"}},
                "url": "freepik_context"
            }
        ]
    }
    
    searcher = ImageSearcher(mock_config)
    results = searcher.search_freepik("test")
    
    assert len(results) == 1
    assert results[0]["thumb"] == "freepik_url"
    assert results[0]["full"] == "freepik_url"
    assert results[0]["context_url"] == "freepik_context"
    assert results[0]["provider"] == "freepik"
        
    # Verify headers contained key
    call_args = mock_requests_get.call_args
    assert call_args[1]['headers']['x-freepik-api-key'] == "fake_freepik_key"
