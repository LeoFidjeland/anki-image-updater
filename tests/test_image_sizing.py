"""Unit tests for image_sizing.py (pure sizing / URL selection, no HTTP)."""

import pytest

import image_sizing as iz


def test_discrete_fetch_target_long_edge():
    assert iz.discrete_fetch_target_long_edge(800, 600, 1920) == 800
    assert iz.discrete_fetch_target_long_edge(5000, 3000, 1920) == 1920
    assert iz.discrete_fetch_target_long_edge(None, 100, 420) == 420


def test_pick_url_from_tiers_smallest_covering():
    bucket = {"a": "url_a", "b": "url_b", "c": "url_c"}
    tiers = (("a", 100), ("b", 500), ("c", 2000))

    assert iz.pick_url_from_tiers(tiers, bucket.get, 50, 50, 1920) == "url_a"
    assert iz.pick_url_from_tiers(tiers, bucket.get, 400, 300, 1920) == "url_b"
    assert iz.pick_url_from_tiers(tiers, bucket.get, 4000, 3000, 1920) == "url_c"


def test_pick_url_from_tiers_missing_url_falls_through():
    bucket = {"a": "", "b": "url_b"}
    tiers = (("a", 100), ("b", 500))
    assert iz.pick_url_from_tiers(tiers, bucket.get, 50, 50, 1920) == "url_b"


def test_unsplash_w_portrait_uses_narrower_param():
    # Portrait: limit long edge 420 → width ≈ 210 for 1000×2000
    assert iz.unsplash_w_for_max_long_edge(1000, 2000, 420) == 210
    assert iz.unsplash_w_for_max_long_edge(4000, 3000, 420) == 420


def test_unsplash_thumb_full_urls_portrait_vs_landscape():
    raw = "https://images.unsplash.com/photo-raw"
    t_land, f_land = iz.unsplash_thumb_full_urls(raw, 4000, 3000)
    assert "w=420" in t_land
    assert "w=1920" in f_land

    t_port, f_port = iz.unsplash_thumb_full_urls(raw, 1000, 2000)
    assert "w=210" in t_port
    assert "w=960" in f_port  # 1920 * 1000 / 2000


def test_pexels_thumb_full_urls_preview_and_save_use_dimensions():
    src = {
        "small": "S",
        "medium": "M",
        "large": "L",
        "large2x": "L2",
        "original": "O",
    }
    # Tiny photo → save target = native long edge; large tier still covers
    thumb, full = iz.pexels_thumb_full_urls(src, 300, 200)
    assert thumb == "M"  # first preview tier >= min(300,420)=300 → medium 400
    assert full == "L"

    # Huge photo → large2x for save
    thumb2, full2 = iz.pexels_thumb_full_urls(src, 5000, 4000)
    assert thumb2 == "L"
    assert full2 == "L2"


def test_pixabay_thumb_full_urls_respects_native_size_for_save():
    hit = {
        "previewURL": "p",
        "webformatURL": "https://ex.com/w_640.jpg",
        "largeImageURL": "lg",
        "fullHDURL": "hd",
        "imageURL": "full",
        "imageWidth": 800,
        "imageHeight": 600,
    }
    thumb, full = iz.pixabay_thumb_full_urls(hit, 800, 600)
    assert "_340." in thumb or "_640." in thumb
    assert full == "lg"  # target min(800,1920)=800, first tier >=800 is largeImageURL 1280


def test_wikimedia_grid_preview_url_prefers_thumburl():
    orig = "https://upload.wikimedia.org/wikipedia/commons/e/ef/Test.jpg"
    api = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Test.jpg/420px-Test.jpg"
    assert iz.wikimedia_grid_preview_url({"url": orig, "thumburl": api}, orig) == api


def test_wikimedia_grid_preview_url_falls_back_to_original_url():
    orig = "https://upload.wikimedia.org/wikipedia/commons/e/ef/Test.jpg"
    assert iz.wikimedia_grid_preview_url({"url": orig}, orig) == orig


def test_wikimedia_save_iiurlwidth_portrait_large():
    assert iz.wikimedia_save_iiurlwidth(1610, 2478) == 1247


def test_wikimedia_save_iiurlwidth_none_when_original_fits_cap():
    assert iz.wikimedia_save_iiurlwidth(1, 1) is None
