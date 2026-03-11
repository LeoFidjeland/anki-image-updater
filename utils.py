import httpx
import base64
import logging

logger = logging.getLogger(__name__)

async def download_image_as_base64(url):
    """Downloads an image URL asynchronously and converts it to base64."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None
