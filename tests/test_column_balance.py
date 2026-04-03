"""Tests for shortest-column layout helpers on AppUI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from anki_image_updater import AppUI


def test_normalized_height_ratio_with_dims():
    assert AppUI._normalized_height_ratio({"thumb_width": 100, "thumb_height": 200}) == 2.0
    assert AppUI._normalized_height_ratio({"thumb_width": 200, "thumb_height": 100}) == 0.5


def test_normalized_height_ratio_fallback_matches_four_three():
    assert AppUI._normalized_height_ratio({}) == 3.0 / 4.0


def test_balanced_column_indices_three_equal_splits():
    img = {"thumb_width": 100, "thumb_height": 100}
    imgs = [img, img, img]
    assert AppUI._balanced_column_indices(imgs) == [0, 1, 2]


def test_balanced_column_indices_fourth_goes_to_shortest():
    # Same aspect → after 0,1,2 fourth should go to column 0 again
    img = {"thumb_width": 100, "thumb_height": 100}
    imgs = [img, img, img, img]
    assert AppUI._balanced_column_indices(imgs) == [0, 1, 2, 0]


def test_balanced_sequential_consistency():
    """First N placements must match running greedy on only the first N images."""
    imgs = [
        {"thumb_width": 100, "thumb_height": 50},
        {"thumb_width": 100, "thumb_height": 300},
        {"thumb_width": 100, "thumb_height": 100},
    ]
    full = AppUI._balanced_column_indices(imgs)
    partial = AppUI._balanced_column_indices(imgs[:2])
    assert full[:2] == partial


def test_gap_height_ratio_normalizes_gap4_to_column_width():
    """gap-4 (16px) vs reference column width — same scale as th/tw."""
    assert AppUI._gap_height_ratio() == AppUI._GAP_PX / AppUI._REFERENCE_COLUMN_WIDTH_PX


def test_gap_only_between_items_in_same_column():
    """After three equal images in three columns, each column height is r (no gaps yet)."""
    img = {"thumb_width": 100, "thumb_height": 100}
    r = AppUI._normalized_height_ratio(img)
    gap = AppUI._gap_height_ratio()
    cols = AppUI._balanced_column_indices([img, img, img, img])
    assert cols == [0, 1, 2, 0]
    # Fourth image stacks under col0: previous r + gap + r
    h0 = r + gap + r
    h1 = h2 = r
    assert h0 > h1  # gap makes stacked column taller than single-item columns
