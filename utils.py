import requests
import base64
import logging

logger = logging.getLogger(__name__)

def download_image_as_base64(url):
    """Downloads an image URL and converts it to base64."""
    try:
        r = requests.get(url)
        r.raise_for_status()
        return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None
