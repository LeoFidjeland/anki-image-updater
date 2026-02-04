import pytest
from image_updater import search_pexels, search_unsplash, search_freepik
# we import module to patch config inside it if needed, 
# but image_updater imports config instance. We need to patch that instance.

def test_search_pexels_no_key(mock_config):
    """Test that pexels search returns empty list if no key."""
    # Ensure key is empty
    mock_config.set("PEXELS_API_KEY", "")
    
    from image_updater import config
    # We need to make sure image_updater.config is our mock_config or has the same state.
    # Since we can't easily replace the imported instance in another module with the fixture 
    # (unless we patch image_updater.config), we will use monkeypatch.
    
    # Actually, verify what ConfigManager our fixture returns. 
    # It patches config_manager.user_config_dir. 
    # If image_updater was already imported, it has its own ConfigManager instance 
    # initialized with the REAL path (if it ran before patch).
    # But pytest imports are handled such that if we patch before import ... 
    
    # Safest way: Patch image_updater.config
    with pytest.MonkeyPatch.context() as m:
        m.setattr("image_updater.config", mock_config)
        results = search_pexels("test")
        assert results == []

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
    
    with pytest.MonkeyPatch.context() as m:
        m.setattr("image_updater.config", mock_config)
        
        results = search_pexels("test")
        
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
    
    with pytest.MonkeyPatch.context() as m:
        m.setattr("image_updater.config", mock_config)
        assert search_unsplash("test") == []
        assert search_freepik("test") == []
