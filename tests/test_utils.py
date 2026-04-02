import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_download_image_as_base64():
    """Test downloading a real small image and converting to base64."""
    from utils import download_image_as_base64
    url = "https://httpbin.org/image/jpeg"
    result = await download_image_as_base64(url)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_download_image_as_base64_follows_redirects():
    """Integration test: ensure redirect URLs are followed."""
    from utils import download_image_as_base64

    # httpbin.org/redirect-to issues a 302 to the target URL.
    url = "https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2Fimage%2Fjpeg"
    result = await download_image_as_base64(url)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0

@pytest.mark.asyncio
async def test_download_image_as_base64_invalid_url():
    """Test that invalid URL returns None without raising."""
    from utils import download_image_as_base64
    result = await download_image_as_base64("http://localhost:9999/nonexistent")
    assert result is None
