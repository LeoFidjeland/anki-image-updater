import html
import httpx
import base64
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


def strip_html_to_plain(html_text: str) -> str:
    """Remove HTML tags; collapse whitespace (same behavior as the GUI left panel)."""
    if not html_text:
        return ""
    s = re.sub(r"<[^>]+>", " ", html_text)
    return re.sub(r"\s+", " ", s).strip()


def _stock_page_query_may_be_stripped(host: str, path: str) -> bool:
    """
    True when the URL is a known “photo / asset page” on a stock site where the
    path alone identifies the resource (UTM, share, SPA hash-params, etc. are junk).

    Never true for Wikimedia index.php, Wikipedia, or obvious CDN hostnames.
    """
    host_l = (host or "").lower()
    path = path or ""
    if "wikimedia.org" in host_l or "wikipedia.org" in host_l:
        return False
    if "/index.php" in path:
        return False

    if any(
        m in host_l
        for m in (
            "img.freepik",
            "cdn.freepik",
            "static.freepik",
            "images.unsplash",
            "plus.unsplash",
            "images.pexels",
            "videos.pexels",
            "cdn.pixabay",
        )
    ):
        return False

    h = host_l[4:] if host_l.startswith("www.") else host_l

    if h == "freepik.com" or (
        h.endswith(".freepik.com") and not h.startswith(("img.", "cdn.", "static."))
    ):
        return True

    if (h == "unsplash.com" or h.endswith(".unsplash.com")) and path.startswith(
        "/photos/"
    ):
        return True

    if (h == "pexels.com" or h.endswith(".pexels.com")) and (
        path.startswith("/photo/") or "/photo/" in path
    ):
        return True

    if (h == "pixabay.com" or h.endswith(".pixabay.com")) and path.startswith(
        ("/photos/", "/illustrations/", "/vectors/", "/videos/")
    ):
        return True

    return False


def normalize_source_url_tracking_junk(url: str) -> str:
    """
    Drop URL fragments (``#…``) for all http(s) URLs — they are client-only.

    For a small allowlist of stock-photo *page* hosts, also drop the query string
    (tracking, share params, SPA state mirrored in the hash, etc.). Other URLs
    keep their query (e.g. Wikimedia ``?title=…``).
    """
    u = html.unescape((url or "").strip())
    if not u:
        return u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return u
    query = p.query
    if _stock_page_query_may_be_stripped(p.netloc, p.path or ""):
        query = ""
    return urlunparse(
        (p.scheme, p.netloc, p.path or "", p.params, query, "")
    )


def strip_wikimedia_oldid_param(url: str) -> str:
    """
    Drop ``oldid`` from the query string on wikimedia.org URLs so revision links
    become the stable file page URL. Preserves the original encoding of other params
    (does not re-encode ``title=`` values).
    """
    u = html.unescape((url or "").strip())
    if not u:
        return u
    p = urlparse(u)
    if "wikimedia.org" not in (p.netloc or "").lower():
        return u
    if not p.query:
        return u
    kept = [
        part
        for part in p.query.split("&")
        if part and not part.lower().startswith("oldid=")
    ]
    if len(kept) == len(p.query.split("&")):
        return u
    new_q = "&".join(kept)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))


def _is_probable_http_url(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    p = urlparse(s)
    return p.scheme in ("http", "https") and bool(p.netloc)


def clean_image_source_field(raw: str) -> Optional[str]:
    """
    From HTML or plain text, derive a single http(s) URL for an image source field.

    Prefer ``href`` from an anchor, else the first http(s) URL in plain text after
    stripping tags, else the whole field if it is already a bare URL. Applies
    :func:`strip_wikimedia_oldid_param` and :func:`normalize_source_url_tracking_junk`.
    Returns ``None`` if no valid URL is found.
    """
    if raw is None or not str(raw).strip():
        return None
    text = str(raw)
    candidate: Optional[str] = None

    m = re.search(r'href\s*=\s*"([^"]+)"', text, re.I)
    if not m:
        m = re.search(r"href\s*=\s*'([^']+)'", text, re.I)
    if m:
        candidate = html.unescape(m.group(1).strip())

    if not candidate or not _is_probable_http_url(candidate):
        plain = html.unescape(re.sub(r"<[^>]+>", " ", text))
        plain = re.sub(r"\s+", " ", plain).strip()
        for m in re.finditer(r"https?://[^\s<>'\"]+", plain):
            u = m.group(0).rstrip(").,;\"'»")
            if _is_probable_http_url(u):
                candidate = u
                break

    if not candidate or not _is_probable_http_url(candidate):
        bare = html.unescape(strip_html_to_plain(text)).strip()
        if _is_probable_http_url(bare):
            candidate = bare

    if not candidate or not _is_probable_http_url(candidate):
        return None
    return normalize_source_url_tracking_junk(
        strip_wikimedia_oldid_param(candidate)
    )

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
