import httpx
import base64
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_VIEWBOX_RE = re.compile(
    r"viewBox\s*=\s*[\"']"
    r"\s*([-\d.eE]+)\s*[, \t]+([-\d.eE]+)\s*[, \t]+([-\d.eE]+)\s*[, \t]+([-\d.eE]+)\s*[\"']",
    re.I,
)


def parse_svg_aspect_dimensions(svg_text: str) -> Optional[Tuple[int, int]]:
    """
    Best-effort intrinsic size from SVG markup: ``viewBox`` width/height, else
    root ``<svg width height>`` (numeric px-like values only).
    """
    if not svg_text or "<svg" not in svg_text[:5000].lower():
        return None
    head = svg_text[:32768]
    m = _VIEWBOX_RE.search(head)
    if m:
        w, h = float(m.group(3)), float(m.group(4))
        if w > 1e-9 and h > 1e-9:
            return max(1, int(round(w))), max(1, int(round(h)))
    tag_m = re.search(r"<svg\b([^>]{0,12000})>", head, re.I | re.DOTALL)
    if not tag_m:
        return None
    attrs = tag_m.group(1)

    def _numeric_attr(name: str) -> Optional[float]:
        am = re.search(r"\b" + name + r'\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
        if not am:
            return None
        v = am.group(1).strip()
        num = re.match(r"^([\d.]+)", v)
        if not num:
            return None
        x = float(num.group(1))
        return x if x > 1e-9 else None

    sw, sh = _numeric_attr("width"), _numeric_attr("height")
    if sw is not None and sh is not None:
        return max(1, int(round(sw))), max(1, int(round(sh)))
    return None

async def download_image_as_base64(url):
    """Downloads an image URL asynchronously and converts it to base64."""
    try:
        headers = {'User-Agent': 'AnkiImageUpdater/1.0 (https://github.com/LeoFidjeland/anki-image-updater; open-source tool)'}
        # Some providers return a 30x redirect to the actual asset URL.
        # httpx doesn't follow redirects by default, so enable it explicitly.
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, max_redirects=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None
