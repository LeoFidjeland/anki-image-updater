"""
Shared image sizing for search providers: long-edge targets, portrait-aware width
parameters, discrete CDN tiers, and Wikimedia Commons thumbnail URLs.

Provider search code should only implement HTTP + JSON parsing; use helpers here
for thumb/full URL selection.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable, Optional, Sequence, Tuple

# Grid cells are a few hundred CSS pixels; keep bitmap long edge near this.
GRID_THUMB_MAX_DIM = 420
# Saved card: we aim for this long edge (discrete tiers may exceed slightly).
SAVE_MAX_DIM = 1920

# --- Presets (smallest value >= target) ------------------------------------

WIKIMEDIA_SAVE_LONG_EDGE_PRESETS = sorted(
    [320, 480, 640, 800, 1024, 1280, 1600, 1920, 2048, 2560, 3072, 3840, 4096]
)
UNSPLASH_W_PRESETS = sorted([320, 480, 640, 1080, 1920, 2560, 3840, 5120])

# Pexels src keys — nominal max long edge (heuristic; API does not publish exacts).
PEXELS_PREVIEW_TIERS: Tuple[Tuple[str, int], ...] = (
    ("small", 200),
    ("medium", 400),
    ("large", 940),
    ("large2x", 2560),
    ("original", 10**9),
)
PEXELS_SAVE_TIERS: Tuple[Tuple[str, int], ...] = (
    ("large", 1280),
    ("large2x", 2560),
    ("original", 10**9),
)

# Pixabay hit keys — nominal long edge.
PIXABAY_PREVIEW_TIERS: Tuple[Tuple[str, int], ...] = (
    ("previewURL", 150),
    ("webformatURL", 640),
)
PIXABAY_SAVE_TIERS: Tuple[Tuple[str, int], ...] = (
    ("webformatURL", 640),
    ("largeImageURL", 1280),
    ("fullHDURL", 1920),
    ("imageURL", 10**9),
)

_COMMONS_THUMB_LAST = re.compile(r"^(\d+)px-(.+)$")


def smallest_preset_ge(presets_asc: Sequence[int], target: int) -> int:
    """Smallest preset >= target; else largest preset."""
    for p in presets_asc:
        if p >= target:
            return p
    return presets_asc[-1]


def wikimedia_save_long_edge_cap() -> int:
    return smallest_preset_ge(WIKIMEDIA_SAVE_LONG_EDGE_PRESETS, SAVE_MAX_DIM)


def unsplash_save_long_edge_cap() -> int:
    return smallest_preset_ge(UNSPLASH_W_PRESETS, SAVE_MAX_DIM)


def width_param_for_max_long_edge(ow, oh, max_long: int) -> Optional[int]:
    """
    Width parameter for CDNs that scale by image WIDTH and height proportionally
    (Commons .../Wpx-..., Unsplash ``w`` with fit=max).

    Returns None if the original already fits within max_long on the long edge
    (caller may use the native asset URL).
    """
    try:
        ow_i, oh_i = int(ow), int(oh)
    except (TypeError, ValueError):
        return max_long
    if ow_i <= 0 or oh_i <= 0:
        return max_long
    if max(ow_i, oh_i) <= max_long:
        return None
    if ow_i >= oh_i:
        return min(ow_i, max_long)
    return max(1, int(round(max_long * ow_i / oh_i)))


def unsplash_w_for_max_long_edge(ow, oh, max_long: int) -> int:
    """Unsplash ``w`` value; falls back to native long edge when already small."""
    wlim = width_param_for_max_long_edge(ow, oh, max_long)
    if wlim is not None:
        return wlim
    try:
        ow_i, oh_i = int(ow), int(oh)
        return max(max(ow_i, oh_i), 1)
    except (TypeError, ValueError):
        return max_long


def discrete_fetch_target_long_edge(ow, oh, cap: int) -> int:
    """
    Long-edge length we want a discrete tier to cover: at most ``cap``, but at
    least the native long edge when the image is smaller than ``cap``.
    """
    try:
        native = max(int(ow), int(oh))
    except (TypeError, ValueError):
        return cap
    if native <= 0:
        return cap
    return min(native, cap)


def pick_url_from_tiers(
    tiers: Sequence[Tuple[str, int]],
    get: Callable[[str], Any],
    ow,
    oh,
    cap: int,
) -> str:
    """Smallest tier with nominal >= discrete_fetch_target_long_edge(ow,oh,cap)."""
    target = discrete_fetch_target_long_edge(ow, oh, cap)
    for key, nominal in tiers:
        if nominal >= target:
            u = get(key)
            if u:
                return str(u)
    return ""


def preview_dims_from_original(orig_w, orig_h, max_dim: int = GRID_THUMB_MAX_DIM) -> dict:
    """Layout thumb_width/thumb_height when the grid scales to max_dim on the long edge."""
    try:
        ow, oh = int(orig_w), int(orig_h)
    except (TypeError, ValueError):
        return {}
    if ow <= 0 or oh <= 0:
        return {}
    long_edge = max(ow, oh)
    if long_edge <= max_dim:
        return thumb_dims(ow, oh)
    scale = max_dim / long_edge
    return thumb_dims(int(round(ow * scale)), int(round(oh * scale)))


def thumb_dims(width, height) -> dict:
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return {}
    if w > 0 and h > 0:
        return {"thumb_width": w, "thumb_height": h}
    return {}


def unsplash_sized_raw_url(raw_url: str, w: int) -> str:
    sep = "&" if "?" in raw_url else "?"
    return f"{raw_url}{sep}w={int(w)}&fit=max&q=80"


# --- Wikimedia Commons ------------------------------------------------------


def commons_thumb_url_from_original(original_url: str, width_px: int) -> str:
    if not original_url or width_px <= 0:
        return original_url
    parsed = urllib.parse.urlparse(original_url)
    path = parsed.path or ""
    if "/thumb/" in path:
        return commons_resize_thumb_url_width(path, width_px, parsed)
    segments = [s for s in path.split("/") if s]
    try:
        commons_idx = segments.index("commons")
    except ValueError:
        return original_url
    if commons_idx + 1 < len(segments) and segments[commons_idx + 1] == "thumb":
        return original_url
    after_commons = segments[commons_idx + 1 :]
    if len(after_commons) < 2:
        return original_url
    filename = after_commons[-1]
    thumb_segments = segments[: commons_idx + 1] + ["thumb"] + after_commons + [f"{width_px}px-{filename}"]
    new_path = "/" + "/".join(thumb_segments)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))


def commons_resize_thumb_url_width(parsed_path: str, width_px: int, parsed) -> str:
    parts = parsed_path.rstrip("/").split("/")
    if not parts:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed_path, "", "", ""))
    last = parts[-1]
    m = _COMMONS_THUMB_LAST.match(last)
    if not m:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed_path, "", "", ""))
    rest = m.group(2)
    parts[-1] = f"{width_px}px-{rest}"
    new_path = "/".join(parts)
    if not new_path.startswith("/"):
        new_path = "/" + new_path
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))


def wikimedia_shrink_existing_thumb_url(save_thumb_url: str, grid_max: int) -> str:
    """Lower W in .../thumb/.../Wpx-...; never upscale."""
    if not save_thumb_url or grid_max <= 0:
        return save_thumb_url
    parsed = urllib.parse.urlparse(save_thumb_url)
    path = parsed.path or ""
    parts = path.rstrip("/").split("/")
    if not parts:
        return save_thumb_url
    m = _COMMONS_THUMB_LAST.match(parts[-1])
    if not m or int(m.group(1)) <= grid_max:
        return save_thumb_url
    return commons_resize_thumb_url_width(path, grid_max, parsed)


def wikimedia_grid_preview_url(info: dict, original_url: str) -> str:
    """
    Grid preview after ``imageinfo`` was requested with ``iiurlwidth=GRID_THUMB_MAX_DIM``.

    MediaWiki does not return a list of “available sizes”; you pass ``iiurlwidth`` / ``iiurlheight``
    and it responds with an authoritative ``thumburl`` (or the original ``url`` when no scaling).
    Never guess or hand-build ``/thumb/.../Wpx-...`` paths for previews.
    """
    info = info or {}
    orig = (original_url or info.get("url") or "").strip()
    return (info.get("thumburl") or "").strip() or orig


def wikimedia_save_iiurlwidth(ow, oh) -> Optional[int]:
    """
    ``iiurlwidth`` to request for the saved image (long-edge cap via ``width_param_for_max_long_edge``).

    ``None`` means the original file already fits the save cap — use ``url`` from ``imageinfo``,
    no second API call.
    """
    cap = wikimedia_save_long_edge_cap()
    return width_param_for_max_long_edge(ow, oh, cap)


def pixabay_webformat_smaller(webformat_url: str) -> str:
    """Prefer ~340px webformat variant when the API gave _640 / _960."""
    if not webformat_url:
        return ""
    return webformat_url.replace("_640.", "_340.").replace("_960.", "_340.")


def pexels_thumb_full_urls(src: Optional[dict], ow, oh) -> Tuple[str, str]:
    src = src or {}
    thumb = pick_url_from_tiers(PEXELS_PREVIEW_TIERS, lambda k: src.get(k), ow, oh, GRID_THUMB_MAX_DIM)
    if not thumb:
        thumb = src.get("medium") or src.get("small") or src.get("large") or ""
    full = pick_url_from_tiers(PEXELS_SAVE_TIERS, lambda k: src.get(k), ow, oh, SAVE_MAX_DIM)
    if not full:
        full = src.get("original") or src.get("large2x") or src.get("large") or ""
    return thumb, full


def pixabay_thumb_full_urls(hit: dict, ow, oh) -> Tuple[str, str]:
    hit = hit or {}
    thumb_pick = pick_url_from_tiers(PIXABAY_PREVIEW_TIERS, lambda k: hit.get(k), ow, oh, GRID_THUMB_MAX_DIM)
    thumb = pixabay_webformat_smaller(thumb_pick) or thumb_pick or hit.get("previewURL", "")
    full = pick_url_from_tiers(PIXABAY_SAVE_TIERS, lambda k: hit.get(k), ow, oh, SAVE_MAX_DIM)
    if not full:
        full = (
            hit.get("imageURL")
            or hit.get("fullHDURL")
            or hit.get("largeImageURL")
            or hit.get("webformatURL")
            or ""
        )
    return thumb, full


def unsplash_thumb_full_urls(raw: str, ow, oh) -> Tuple[str, str]:
    tw = unsplash_w_for_max_long_edge(ow, oh, GRID_THUMB_MAX_DIM)
    sw = unsplash_w_for_max_long_edge(ow, oh, unsplash_save_long_edge_cap())
    return unsplash_sized_raw_url(raw, tw), unsplash_sized_raw_url(raw, sw)
