#!/usr/bin/env bash
# Build packaging/macos/AppIcon.icns from a square PNG (macOS only).
#
# Usage:
#   ./scripts/generate_macos_icon.sh [path/to/source.png]
#
# Default source: packaging/macos/anki-image-updater-icon.png

set -euo pipefail
export COPYFILE_DISABLE=1

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must run on macOS (sips + iconutil)." >&2
    exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
src="${1:-$repo_root/packaging/macos/anki-image-updater-icon.png}"
out_icns="$repo_root/packaging/macos/AppIcon.icns"

if [[ ! -f "$src" ]]; then
    echo "Source PNG not found: $src" >&2
    exit 1
fi

tmp="$repo_root/.icon-build.iconset"
rm -rf "$tmp"
mkdir -p "$tmp"

sips -z 16 16   "$src" --out "$tmp/icon_16x16.png"
sips -z 32 32   "$src" --out "$tmp/icon_16x16@2x.png"
sips -z 32 32   "$src" --out "$tmp/icon_32x32.png"
sips -z 64 64   "$src" --out "$tmp/icon_32x32@2x.png"
sips -z 128 128 "$src" --out "$tmp/icon_128x128.png"
sips -z 256 256 "$src" --out "$tmp/icon_128x128@2x.png"
sips -z 256 256 "$src" --out "$tmp/icon_256x256.png"
sips -z 512 512 "$src" --out "$tmp/icon_256x256@2x.png"
sips -z 512 512 "$src" --out "$tmp/icon_512x512.png"
sips -z 1024 1024 "$src" --out "$tmp/icon_512x512@2x.png"

xattr -cr "$tmp"
iconutil -c icns "$tmp" -o "$out_icns"
xattr -cr "$out_icns"
rm -rf "$tmp"

echo "Wrote $out_icns"
ls -lh "$out_icns"
