import httpx
import base64
import logging

logger = logging.getLogger(__name__)

async def download_image_as_base64(url):
    """Downloads an image URL asynchronously and converts it to base64."""
    try:
        headers = {'User-Agent': 'AnkiImageUpdater/1.0 (https://github.com/anki-image-updater; open-source tool)'}
        # Some providers return a 30x redirect to the actual asset URL.
        # httpx doesn't follow redirects by default, so enable it explicitly.
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, max_redirects=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None
