import httpx
import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)

# Grid: ~3–4 columns; each cell is only a few hundred CSS pixels wide — fetch light thumbs
# (~400px long edge) so we are not loading 1600px images per cell. Retina-friendly without waste.
GRID_THUMB_MAX_DIM = 420
# Saved card image: “large” quality (~1920px long edge) where the API supports it.
SAVE_MAX_DIM = 1920


def _thumb_dims(width, height):
    """Return dict with thumb_width/thumb_height if both are positive ints, else {}."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return {}
    if w > 0 and h > 0:
        return {"thumb_width": w, "thumb_height": h}
    return {}


def _parse_freepik_source_size(image_obj):
    """Parse image.source.size like '740x640' or '740×640' into (w, h)."""
    if not isinstance(image_obj, dict):
        return None, None
    src = image_obj.get("source") or {}
    size = src.get("size")
    if not size:
        return None, None
    size_str = str(size).replace("\u00d7", "x").replace("×", "x")
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", size_str)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _preview_dims_from_original(orig_w, orig_h, max_dim=GRID_THUMB_MAX_DIM):
    """Dimensions for layout when the preview is scaled to max long edge max_dim."""
    try:
        ow, oh = int(orig_w), int(orig_h)
    except (TypeError, ValueError):
        return {}
    if ow <= 0 or oh <= 0:
        return {}
    long_edge = max(ow, oh)
    if long_edge <= max_dim:
        return _thumb_dims(ow, oh)
    scale = max_dim / long_edge
    return _thumb_dims(int(round(ow * scale)), int(round(oh * scale)))


def _unsplash_raw_width(raw_url: str, width: int) -> str:
    """Resize Unsplash hotlinked `raw` URL to a max width (long edge for landscape)."""
    sep = "&" if "?" in raw_url else "?"
    return f"{raw_url}{sep}w={width}&fit=max&q=80"


def _pixabay_grid_thumb_url(webformat_url: str) -> str:
    """Prefer ~340px webformat variant for grid (Pixabay allows swapping _640 → _340 in path)."""
    if not webformat_url:
        return ""
    # e.g. ..._640.jpg → ..._340.jpg (see Pixabay API docs for webformatURL)
    return webformat_url.replace("_640.", "_340.").replace("_960.", "_340.")


class ImageSearcher:
    """Handles communicating with external image APIs asynchronously."""
    
    def __init__(self, config_manager):
        self.config = config_manager

    def parse_api_error(self, response):
        """Centralized helper for API requests that raises explicit auth errors."""
        try:
            if response.status_code == 401:
                raise ValueError("API key is invalid or unauthorized. Please check your settings.")
            if response.status_code == 403:
                raise Exception(f"Request rejected (403) — you may be temporarily rate-limited. Try again in a moment or switch provider.")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP Error: {e}")
            raise Exception(f"API Error ({response.status_code}): {e}")

    async def make_search_request(self, url, headers):
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            return self.parse_api_error(r)

    async def search(self, provider, query, count=1, page=1):
        if provider == 'pexels':
            return await self.search_pexels(query, count, page)
        elif provider == 'unsplash':
            return await self.search_unsplash(query, count, page)
        elif provider == 'freepik':
            return await self.search_freepik(query, count, page)
        elif provider == 'pixabay':
            return await self.search_pixabay(query, count, page)
        elif provider == 'wikimedia':
            return await self.search_wikimedia(query, count, page)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def search_pexels(self, query, count=1, page=1):
        """Searches Pexels."""
        api_key = self.config.get("PEXELS_API_KEY")
        if not api_key: 
            raise ValueError("Pexels API key is missing. Please add it in Settings.")
        
        headers = {'Authorization': api_key}
        url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}&page={page}"
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('photos'):
            for photo in data['photos']:
                src = photo.get('src') or {}
                # Grid: medium (~350px tall) — not large2x. Save: large2x / large / original.
                thumb_url = src.get('medium') or src.get('small') or src.get('large')
                full_url = src.get('large2x') or src.get('large') or src.get('original')
                results.append({
                    'thumb': thumb_url,
                    'full': full_url,
                    'context_url': photo['url'],
                    'provider': 'Pexels',
                    **_preview_dims_from_original(photo.get('width'), photo.get('height')),
                })
        return results

    async def search_unsplash(self, query, count=1, page=1):
        """Searches Unsplash."""
        access_key = self.config.get("UNSPLASH_ACCESS_KEY")
        if not access_key:
            raise ValueError("Unsplash API key is missing. Please add it in Settings.")
        
        headers = {'Authorization': f'Client-ID {access_key}'}
        url = f"https://api.unsplash.com/search/photos?query={query}&per_page={count}&page={page}"
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('results'):
            for photo in data['results']:
                raw = photo['urls']['raw']
                results.append({
                    'thumb': _unsplash_raw_width(raw, GRID_THUMB_MAX_DIM),
                    'full': _unsplash_raw_width(raw, SAVE_MAX_DIM),
                    'context_url': photo['links']['html'],
                    'provider': 'Unsplash',
                    **_preview_dims_from_original(photo.get('width'), photo.get('height')),
                })
        return results

    async def search_freepik(self, query, count=1, page=1):
        """Searches Freepik."""
        api_key = self.config.get("FREEPIK_API_KEY")
        if not api_key: 
            raise ValueError("Freepik API key is missing. Please add it in Settings.")
        
        headers = {'x-freepik-api-key': api_key}
        # Freepik supports deepObject filters. Use license filtering so we
        # prefer royalty-free assets over premium ones.
        params = {
            "term": query,
            "limit": count,
            "page": page,
            "filters[license][freemium]": 1,
        }
        url = "https://api.freepik.com/v1/resources?" + urllib.parse.urlencode(params)
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('data'):
            for item in data['data']:
                # Defensive client-side filtering in case the API returns mixed license types.
                licenses = item.get("licenses")
                if isinstance(licenses, list):
                    license_types = {
                        lic.get("type")
                        for lic in licenses
                        if isinstance(lic, dict) and lic.get("type")
                    }
                    free_types = {"freemium", "essential"}
                    if "premium" in license_types:
                        continue
                    if license_types and not (license_types & free_types):
                        continue
                if 'image' in item and 'source' in item['image']:
                    fw, fh = _parse_freepik_source_size(item['image'])
                    url = item['image']['source']['url']
                    results.append({
                        'thumb': url,
                        'full': url,
                        'context_url': item.get('url', '#'),
                        'provider': 'Freepik',
                        **_preview_dims_from_original(fw, fh, max_dim=GRID_THUMB_MAX_DIM),
                    })
        return results

    async def search_pixabay(self, query, count=1, page=1):
        """Searches Pixabay (https://pixabay.com/api/docs/)."""
        api_key = self.config.get("PIXABAY_API_KEY")
        if not api_key:
            raise ValueError("Pixabay API key is missing. Please add it in Settings.")

        # per_page must be 3–200; request enough rows then trim to count.
        per_page = max(3, min(count, 200))
        params = {
            "key": api_key,
            "q": query[:100],
            "page": page,
            "per_page": per_page,
        }
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)

        data = await self.make_search_request(url, headers={})
        results = []
        for hit in data.get("hits", [])[:count]:
            wf = hit.get("webformatURL", "")
            # Grid: ~340px webformat variant; save: full HD / large when available.
            thumb = _pixabay_grid_thumb_url(wf) or wf or hit.get("previewURL", "")
            full = hit.get("fullHDURL") or hit.get("largeImageURL") or wf or ""
            results.append({
                "thumb": thumb,
                "full": full,
                "context_url": hit.get("pageURL", ""),
                "provider": "Pixabay",
                **_preview_dims_from_original(
                    hit.get("imageWidth"), hit.get("imageHeight"), max_dim=GRID_THUMB_MAX_DIM
                ),
            })
        return results

    async def search_wikimedia(self, query, count=1, page=1):
        """Searches Wikimedia Commons. Free, no API key required."""
        import urllib.parse
        # Wikimedia paginates via offset, not page numbers
        offset = (page - 1) * count
        # Fetch extra candidates so we have enough after filtering non-images
        limit = min(count * 3, 50)
        params = {
            'action': 'query',
            'generator': 'search',
            'gsrnamespace': '6',   # File: namespace only
            'gsrsearch': query,
            'gsrlimit': str(limit),
            'gsroffset': str(offset),
            'prop': 'imageinfo',
            'iiprop': 'url|mime',
            # Grid-sized thumb only; `full` uses original `url` (see below).
            'iiurlwidth': str(GRID_THUMB_MAX_DIM),
            'format': 'json',
            'origin': '*',
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Wikimedia API requires a descriptive User-Agent; blocks anonymous bots
            headers = {'User-Agent': 'AnkiImageUpdater/1.0 (https://github.com/anki-image-updater; open-source tool)'}
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()

        results = []
        pages = data.get('query', {}).get('pages', {})
        # Wikimedia generator search returns "pages" as an object (dict),
        # so iterating values() doesn't preserve ranking/offset order.
        # The API includes an `index` field per result; sort by it so that
        # pagination/truncation behaves predictably.
        ordered_pages = sorted(pages.values(), key=lambda p: p.get('index', 0))
        for page_data in ordered_pages:
            if len(results) >= count:
                break
            imageinfo = page_data.get('imageinfo', [])
            if not imageinfo:
                continue
            info = imageinfo[0]
            mime = info.get('mime', '')
            # Skip non-raster images (PDFs, SVGs, audio/video, etc.)
            if not mime.startswith('image/') or mime == 'image/svg+xml':
                continue
            title = page_data.get('title', '')
            context_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(' ', '_'))
            tw = info.get('thumbwidth') or info.get('width')
            th = info.get('thumbheight') or info.get('height')
            thumb_url = info.get('thumburl') or info.get('url', '')
            full_url = info.get('url') or thumb_url
            results.append({
                'thumb': thumb_url,
                'full': full_url,
                'context_url': context_url,
                'provider': 'Wikimedia',
                **_thumb_dims(tw, th),
            })
        return results
