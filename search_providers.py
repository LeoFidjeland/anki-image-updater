import asyncio
import httpx
import logging
import urllib.parse
from collections import defaultdict

from image_sizing import (
    GRID_THUMB_MAX_DIM,
    SAVE_MAX_DIM,
    preview_dims_from_original,
    pexels_thumb_full_urls,
    pixabay_thumb_full_urls,
    thumb_dims,
    unsplash_thumb_full_urls,
    wikimedia_grid_preview_url,
    wikimedia_save_iiurlwidth,
    wikimedia_shrink_existing_thumb_url,
)

logger = logging.getLogger(__name__)

# Re-export for callers/tests that import constants from this module.
__all__ = ["ImageSearcher", "GRID_THUMB_MAX_DIM", "SAVE_MAX_DIM"]

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"


async def _wikimedia_imageinfo_by_title(
    client: httpx.AsyncClient,
    headers: dict,
    titles: list[str],
    iiurlwidth: int,
) -> dict[str, dict]:
    """Map page title -> ``imageinfo[0]`` (``thumburl`` / ``url``) for a fixed ``iiurlwidth``."""
    out: dict[str, dict] = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i : i + 50]
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": str(iiurlwidth),
            "format": "json",
            "origin": "*",
        }
        api_url = _COMMONS_API + "?" + urllib.parse.urlencode(params)
        r = await client.get(api_url, headers=headers)
        r.raise_for_status()
        data = r.json()
        for p in data.get("query", {}).get("pages", {}).values():
            if p.get("missing"):
                continue
            tit = p.get("title")
            ii = p.get("imageinfo") or []
            if tit and ii:
                out[tit] = ii[0]
    return out


def _parse_freepik_source_size(image_obj):
    """Parse image.source.size like '740x640' or '740×640' into (w, h)."""
    import re

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


class ImageSearcher:
    """Handles communicating with external image APIs asynchronously."""

    def __init__(self, config_manager):
        self.config = config_manager
        self._search_cache: dict[tuple, list] = {}
        self._inflight: dict[tuple, asyncio.Task] = {}
        self._search_lock = asyncio.Lock()

    def clear_search_cache(self) -> None:
        """Drop cached search results (new card or new deck load)."""
        self._search_cache.clear()
        for t in list(self._inflight.values()):
            if not t.done():
                t.cancel()
        self._inflight.clear()

    @staticmethod
    def _search_cache_key(provider: str, query: str, count: int, page: int) -> tuple:
        q = (query or "").strip().lower()
        return (provider, q, int(count), int(page))

    def parse_api_error(self, response):
        """Centralized helper for API requests that raises explicit auth errors."""
        try:
            if response.status_code == 401:
                raise ValueError("API key is invalid or unauthorized. Please check your settings.")
            if response.status_code == 403:
                raise Exception(
                    f"Request rejected (403) — you may be temporarily rate-limited. Try again in a moment or switch provider."
                )
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
        """Dispatch to provider search with cache + in-flight deduplication."""
        key = self._search_cache_key(provider, query, count, page)
        if key in self._search_cache:
            return [dict(item) for item in self._search_cache[key]]

        async with self._search_lock:
            if key in self._search_cache:
                return [dict(item) for item in self._search_cache[key]]
            if key not in self._inflight:
                self._inflight[key] = asyncio.create_task(
                    self._search_uncached(provider, query, count, page)
                )
            task = self._inflight[key]

        try:
            results = await task
        except asyncio.CancelledError:
            async with self._search_lock:
                self._inflight.pop(key, None)
            raise
        except BaseException:
            async with self._search_lock:
                self._inflight.pop(key, None)
            raise

        async with self._search_lock:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)
            if key not in self._search_cache:
                self._search_cache[key] = [dict(item) for item in results]

        return [dict(item) for item in results]

    async def _search_uncached(self, provider, query, count=1, page=1):
        if provider == "pexels":
            return await self.search_pexels(query, count, page)
        if provider == "unsplash":
            return await self.search_unsplash(query, count, page)
        if provider == "freepik":
            return await self.search_freepik(query, count, page)
        if provider == "pixabay":
            return await self.search_pixabay(query, count, page)
        if provider == "wikimedia":
            return await self.search_wikimedia(query, count, page)
        raise ValueError(f"Unknown provider: {provider}")

    async def search_pexels(self, query, count=1, page=1):
        """Searches Pexels."""
        api_key = self.config.get("PEXELS_API_KEY")
        if not api_key:
            raise ValueError("Pexels API key is missing. Please add it in Settings.")

        headers = {"Authorization": api_key}
        url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}&page={page}"

        data = await self.make_search_request(url, headers)
        results = []
        if data.get("photos"):
            for photo in data["photos"]:
                src = photo.get("src") or {}
                ow, oh = photo.get("width"), photo.get("height")
                thumb_url, full_url = pexels_thumb_full_urls(src, ow, oh)
                results.append(
                    {
                        "thumb": thumb_url,
                        "full": full_url,
                        "context_url": photo["url"],
                        "provider": "Pexels",
                        **preview_dims_from_original(ow, oh),
                    }
                )
        return results

    async def search_unsplash(self, query, count=1, page=1):
        """Searches Unsplash."""
        access_key = self.config.get("UNSPLASH_ACCESS_KEY")
        if not access_key:
            raise ValueError("Unsplash API key is missing. Please add it in Settings.")

        headers = {"Authorization": f"Client-ID {access_key}"}
        url = f"https://api.unsplash.com/search/photos?query={query}&per_page={count}&page={page}"

        data = await self.make_search_request(url, headers)
        results = []
        if data.get("results"):
            for photo in data["results"]:
                raw = photo["urls"]["raw"]
                ow, oh = photo.get("width"), photo.get("height")
                thumb_url, full_url = unsplash_thumb_full_urls(raw, ow, oh)
                results.append(
                    {
                        "thumb": thumb_url,
                        "full": full_url,
                        "context_url": photo["links"]["html"],
                        "provider": "Unsplash",
                        **preview_dims_from_original(ow, oh),
                    }
                )
        return results

    async def search_freepik(self, query, count=1, page=1):
        """Searches Freepik."""
        api_key = self.config.get("FREEPIK_API_KEY")
        if not api_key:
            raise ValueError("Freepik API key is missing. Please add it in Settings.")

        headers = {"x-freepik-api-key": api_key}
        params = {
            "term": query,
            "limit": count,
            "page": page,
            "filters[license][freemium]": 1,
        }
        url = "https://api.freepik.com/v1/resources?" + urllib.parse.urlencode(params)

        data = await self.make_search_request(url, headers)
        results = []
        if data.get("data"):
            for item in data["data"]:
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
                if "image" in item and "source" in item["image"]:
                    fw, fh = _parse_freepik_source_size(item["image"])
                    img_url = item["image"]["source"]["url"]
                    results.append(
                        {
                            "thumb": img_url,
                            "full": img_url,
                            "context_url": item.get("url", "#"),
                            "provider": "Freepik",
                            **preview_dims_from_original(fw, fh, max_dim=GRID_THUMB_MAX_DIM),
                        }
                    )
        return results

    async def search_pixabay(self, query, count=1, page=1):
        """Searches Pixabay (https://pixabay.com/api/docs/)."""
        api_key = self.config.get("PIXABAY_API_KEY")
        if not api_key:
            raise ValueError("Pixabay API key is missing. Please add it in Settings.")

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
            ow, oh = hit.get("imageWidth"), hit.get("imageHeight")
            thumb_url, full_url = pixabay_thumb_full_urls(hit, ow, oh)
            results.append(
                {
                    "thumb": thumb_url,
                    "full": full_url,
                    "context_url": hit.get("pageURL", ""),
                    "provider": "Pixabay",
                    **preview_dims_from_original(ow, oh, max_dim=GRID_THUMB_MAX_DIM),
                }
            )
        return results

    async def search_wikimedia(self, query, count=1, page=1):
        """Searches Wikimedia Commons. Free, no API key required."""
        offset = (page - 1) * count
        limit = min(count * 3, 50)
        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": str(limit),
            "gsroffset": str(offset),
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            # Authoritative grid thumb: API returns ``thumburl`` for this width (no client-built /thumb/).
            "iiurlwidth": str(GRID_THUMB_MAX_DIM),
            "format": "json",
            "origin": "*",
        }
        url = _COMMONS_API + "?" + urllib.parse.urlencode(params)

        headers = {
            "User-Agent": "AnkiImageUpdater/1.0 (https://github.com/LeoFidjeland/anki-image-updater; open-source tool)"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()

            rows: list[dict] = []
            pages = data.get("query", {}).get("pages", {})
            ordered_pages = sorted(pages.values(), key=lambda p: p.get("index", 0))
            for page_data in ordered_pages:
                if len(rows) >= count:
                    break
                imageinfo = page_data.get("imageinfo", [])
                if not imageinfo:
                    continue
                info = imageinfo[0]
                mime = info.get("mime", "")
                if not mime.startswith("image/") or mime == "image/svg+xml":
                    continue
                title = page_data.get("title", "")
                original_url = (info.get("url") or "").strip()
                ow, oh = info.get("width"), info.get("height")
                thumb_url = wikimedia_grid_preview_url(info, original_url)
                api_thumb = (info.get("thumburl") or "").strip()
                if (
                    api_thumb
                    and thumb_url == api_thumb
                    and info.get("thumbwidth")
                    and info.get("thumbheight")
                ):
                    layout_dims = thumb_dims(info["thumbwidth"], info["thumbheight"])
                else:
                    layout_dims = preview_dims_from_original(ow, oh)

                save_w = wikimedia_save_iiurlwidth(ow, oh)
                rows.append(
                    {
                        "title": title,
                        "info": info,
                        "original_url": original_url,
                        "thumb_url": thumb_url,
                        "layout_dims": layout_dims,
                        "save_w": save_w,
                    }
                )

            by_save_w: dict = defaultdict(list)
            for row in rows:
                by_save_w[row["save_w"]].append(row)

            full_by_title: dict[str, str] = {}
            for save_w, group in by_save_w.items():
                if save_w is None:
                    for row in group:
                        full_by_title[row["title"]] = row["original_url"] or row["info"].get("url") or ""
                    continue
                titles = [row["title"] for row in group]
                batch = await _wikimedia_imageinfo_by_title(client, headers, titles, int(save_w))
                for row in group:
                    tit = row["title"]
                    bi = batch.get(tit)
                    if bi:
                        fu = (bi.get("thumburl") or bi.get("url") or "").strip()
                        full_by_title[tit] = fu or row["original_url"]
                    else:
                        full_by_title[tit] = row["original_url"] or row["info"].get("url") or ""

            results = []
            for row in rows:
                context_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
                    row["title"].replace(" ", "_")
                )
                results.append(
                    {
                        "thumb": row["thumb_url"],
                        "full": full_by_title.get(row["title"], row["original_url"]),
                        "context_url": context_url,
                        "provider": "Wikimedia",
                        **row["layout_dims"],
                    }
                )

        return results


# Back-compat names for tests and any external imports
_preview_dims_from_original = preview_dims_from_original
_wikimedia_grid_thumb_url = wikimedia_shrink_existing_thumb_url
