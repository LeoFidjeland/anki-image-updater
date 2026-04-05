import pytest
from unittest.mock import AsyncMock, MagicMock

from utils import (
    clean_image_source_field,
    normalize_source_url_tracking_junk,
    parse_svg_aspect_dimensions,
    strip_html_to_plain,
    strip_wikimedia_oldid_param,
)


def test_parse_svg_aspect_dimensions_viewbox():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"></svg>'
    assert parse_svg_aspect_dimensions(svg) == (100, 50)


def test_parse_svg_aspect_dimensions_width_height():
    svg = "<svg width=\"200\" height=\"80\" xmlns=\"http://www.w3.org/2000/svg\"></svg>"
    assert parse_svg_aspect_dimensions(svg) == (200, 80)


def test_parse_svg_aspect_dimensions_viewbox_commas():
    svg = "<svg viewBox='0,0,24,24'></svg>"
    assert parse_svg_aspect_dimensions(svg) == (24, 24)


def test_parse_svg_aspect_dimensions_invalid_returns_none():
    assert parse_svg_aspect_dimensions("") is None
    assert parse_svg_aspect_dimensions("<html></html>") is None


def test_strip_html_to_plain():
    assert strip_html_to_plain("<b>a</b> c") == "a c"


def test_strip_wikimedia_oldid_param():
    u = (
        "https://commons.wikimedia.org/w/index.php?"
        "title=File:Foo.jpg&amp;oldid=1071028312"
    )
    out = strip_wikimedia_oldid_param(u)
    assert "oldid" not in out
    assert "title=File:Foo.jpg" in out


def test_clean_image_source_field_href_and_oldid():
    raw = (
        '<a href="https://commons.wikimedia.org/w/index.php?'
        'title=File:Test.jpg&amp;oldid=99">x</a>'
    )
    assert clean_image_source_field(raw) == (
        "https://commons.wikimedia.org/w/index.php?title=File:Test.jpg"
    )


def test_clean_image_source_field_plain_url():
    u = "https://example.com/a?x=1"
    assert clean_image_source_field(u) == u


def test_clean_image_source_field_no_url():
    assert clean_image_source_field("just text") is None


def test_clean_image_source_plain_text_with_html_entities():
    raw = (
        "https://commons.wikimedia.org/w/index.php?"
        "title=File:Z.jpg&amp;oldid=1071028312"
    )
    assert clean_image_source_field(raw) == (
        "https://commons.wikimedia.org/w/index.php?title=File:Z.jpg"
    )


def test_normalize_source_url_strips_hash_everywhere():
    u = "https://example.com/path?keep=1#frag"
    assert normalize_source_url_tracking_junk(u) == "https://example.com/path?keep=1"


def test_normalize_source_url_freepik_hash_spa_junk():
    u = (
        "https://www.freepik.com/free-photo/indoor-shot-carefree-charming-man-red-t-shirt_10176631.htm"
        "#fromView=search&page=1&position=4&uuid=a3f45860-d0f1-4f09-af34-9abc7c1a5d95"
    )
    assert normalize_source_url_tracking_junk(u) == (
        "https://www.freepik.com/free-photo/indoor-shot-carefree-charming-man-red-t-shirt_10176631.htm"
    )


def test_normalize_source_url_unsplash_strips_query_not_cdn():
    u = "https://unsplash.com/photos/abc?utm_source=x&share=copy"
    assert normalize_source_url_tracking_junk(u) == "https://unsplash.com/photos/abc"
    cdn = "https://images.unsplash.com/photo-1?w=400&q=80"
    assert normalize_source_url_tracking_junk(cdn) == cdn


def test_normalize_source_url_wikimedia_keeps_title_query():
    u = "https://commons.wikimedia.org/w/index.php?title=File:A.jpg#filehistory"
    assert normalize_source_url_tracking_junk(u) == (
        "https://commons.wikimedia.org/w/index.php?title=File:A.jpg"
    )

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
