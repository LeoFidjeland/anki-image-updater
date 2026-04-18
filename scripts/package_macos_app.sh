#!/usr/bin/env bash
# Build Anki Image Updater.app from a PyApp Mach-O binary, then zip it for distribution.
#
# Usage:
#   ./scripts/package_macos_app.sh <path-to-binary> <output.zip>
#
# Optional icon: place packaging/macos/AppIcon.icns in the repo (see README).
#
# Requires macOS: ditto, PlistBuddy, swiftc (Xcode CLT), codesign.

set -euo pipefail
# Avoid AppleDouble files (._*) in the zip when copying across filesystems.
export COPYFILE_DISABLE=1

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must run on macOS." >&2
    exit 1
fi

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <path-to-AnkiImageUpdater-binary> <output.zip>" >&2
    exit 1
fi

binary="$1"
zip_out="$2"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$binary" || ! -x "$binary" ]]; then
    echo "Binary not found or not executable: $binary" >&2
    exit 1
fi

version="$(grep -E '^version = ' "$repo_root/pyproject.toml" | head -1 | sed -E 's/^version = "([^"]+)".*/\1/')"
if [[ -z "$version" ]]; then
    echo "Could not read version from pyproject.toml" >&2
    exit 1
fi

app_name="Anki Image Updater.app"
staging="$repo_root/dist-bin/app-staging"
rm -rf "$staging"
mkdir -p "$staging"

app="$staging/$app_name"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
mkdir -p "$app/Contents/Resources"

# PyApp runtime (downloaded / built separately) — real payload.
cp "$binary" "$app/Contents/MacOS/AnkiImageUpdaterPyApp"
chmod +x "$app/Contents/MacOS/AnkiImageUpdaterPyApp"

# Thin Swift launcher: progress UI while PyApp bootstraps, then hands off to NiceGUI in the browser.
swiftc -O \
    -framework AppKit \
    -framework CryptoKit \
    -o "$app/Contents/MacOS/AnkiImageUpdater" \
    "$repo_root/packaging/macos/launcher/main.swift"
chmod +x "$app/Contents/MacOS/AnkiImageUpdater"

sed "s/__VERSION__/${version}/g" "$repo_root/packaging/macos/Info.plist.in" > "$app/Contents/Info.plist"

icon_src="$repo_root/packaging/macos/AppIcon.icns"
if [[ -f "$icon_src" ]]; then
    cp "$icon_src" "$app/Contents/Resources/AppIcon.icns"
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$app/Contents/Info.plist"
fi

# Ad-hoc signing improves Gatekeeper messaging (often "unidentified developer" +
# Privacy & Security → Open Anyway) vs. the misleading "app is damaged" dialog on
# completely unsigned bundles. Not a substitute for Apple Developer ID + notarization.
codesign --force --deep --sign - "$app"

mkdir -p "$(dirname "$zip_out")"
rm -f "$zip_out"
ditto -c -k --keepParent --norsrc --noextattr "$app" "$zip_out"

echo "Packaged: $zip_out"
ls -lh "$zip_out"
