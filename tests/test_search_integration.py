import pytest
from unittest.mock import AsyncMock, MagicMock
from search_providers import ImageSearcher

def test_integration_pexels(real_config):
    """Real integration test for Pexels search."""
    api_key = real_config.get("PEXELS_API_KEY")
    if not api_key:
        pytest.skip("Pexels API key not found in real config. Skipping integration test.")


@pytest.mark.asyncio
async def test_integration_pexels_async(real_config):
    """Real async integration test for Pexels search."""
    api_key = real_config.get("PEXELS_API_KEY")
    if not api_key:
        pytest.skip("Pexels API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = await searcher.search_pexels("dog", count=1)
    
    assert len(results) == 1
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "Pexels"

@pytest.mark.asyncio
async def test_integration_unsplash_async(real_config):
    """Real async integration test for Unsplash search."""
    api_key = real_config.get("UNSPLASH_ACCESS_KEY")
    if not api_key:
        pytest.skip("Unsplash API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = await searcher.search_unsplash("dog", count=1)
    
    assert len(results) == 1
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "Unsplash"

@pytest.mark.asyncio
async def test_integration_freepik_async(real_config):
    """Real async integration test for Freepik search."""
    api_key = real_config.get("FREEPIK_API_KEY")
    if not api_key:
        pytest.skip("Freepik API key not found in real config. Skipping integration test.")
        
    searcher = ImageSearcher(real_config)
    results = await searcher.search_freepik("dog", count=1)
    
    assert len(results) > 0
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "Freepik"

    # Heuristic check: Freepik's "premium" assets typically use "premium-*"
    # in the asset URL path. Since we request freemium/essential only, we
    # should not see "premium" in the returned image URL.
    assert "premium" not in results[0]["thumb"].lower()

@pytest.mark.asyncio
async def test_integration_pixabay_async(real_config):
    """Real async integration test for Pixabay search."""
    api_key = real_config.get("PIXABAY_API_KEY")
    if not api_key:
        pytest.skip("Pixabay API key not found in real config. Skipping integration test.")

    searcher = ImageSearcher(real_config)
    results = await searcher.search_pixabay("dog", count=1)

    assert len(results) == 1
    assert "thumb" in results[0]
    assert "full" in results[0]
    assert "context_url" in results[0]
    assert results[0]["provider"] == "Pixabay"
