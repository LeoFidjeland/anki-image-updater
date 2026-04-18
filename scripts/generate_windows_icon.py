#!/usr/bin/env python3
"""Write packaging/windows/AppIcon.ico from packaging/macos/anki-image-updater-icon.png.

Run (no project dependency on Pillow):
  uv run --with pillow python scripts/generate_windows_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        print("Install Pillow, e.g.: uv run --with pillow python scripts/generate_windows_icon.py", file=sys.stderr)
        sys.exit(1)

    root = Path(__file__).resolve().parents[1]
    src = root / "packaging/macos/anki-image-updater-icon.png"
    dst = root / "packaging/windows/AppIcon.ico"
    if not src.is_file():
        print(f"Missing source PNG: {src}", file=sys.stderr)
        sys.exit(1)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [img.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    # Pillow's ICO writer treats the *first* image's size as the maximum; smaller bases
    # would skip large icons. Use the largest frame as the save() primary image.
    base = imgs[-1]
    rest = imgs[:-1]
    base.save(
        dst,
        format="ICO",
        sizes=[(i.width, i.height) for i in imgs],
        append_images=rest,
    )
    print(f"Wrote {dst}")


if __name__ == "__main__":
    main()
