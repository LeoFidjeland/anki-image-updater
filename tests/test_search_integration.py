import pytest
from search_providers import ImageSearcher

def test_integration_pexels(real_config):
    """Real integration test for Pexels search."""
    api_key = real_config.get("PEXELS_API_KEY")
    if not api_key:
        pytest.skip("Pexels API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = searcher.search_pexels("dog", count=1)
    
    assert len(results) == 1
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "pexels"

def test_integration_unsplash(real_config):
    """Real integration test for Unsplash search."""
    api_key = real_config.get("UNSPLASH_ACCESS_KEY")
    if not api_key:
        pytest.skip("Unsplash API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = searcher.search_unsplash("dog", count=1)
    
    assert len(results) == 1
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "unsplash"

def test_integration_freepik(real_config):
    """Real integration test for Freepik search."""
    api_key = real_config.get("FREEPIK_API_KEY")
    if not api_key:
        pytest.skip("Freepik API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = searcher.search_freepik("dog", count=1)
    
    # Freepik might not strictly return 1 result if it doesn't match well, but for "dog" it should
    assert len(results) > 0
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "freepik"
