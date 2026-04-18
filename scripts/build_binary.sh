#!/usr/bin/env bash
# Build a single-file PyApp binary from the current source.
#
# Requires:
#   - uv  (https://docs.astral.sh/uv/)
#   - cargo / rustc  (e.g. `brew install rust` on macOS)
#
# Output: dist-bin/bin/AnkiImageUpdater[.exe]

set -euo pipefail

cd "$(dirname "$0")/.."

echo ">> Cleaning previous build artifacts"
rm -rf dist dist-bin

echo ">> Building wheel"
uv build --wheel

wheel=$(ls dist/anki_image_updater-*-py3-none-any.whl | head -n1)
echo ">> Wheel: $wheel"

echo ">> Building PyApp bootstrapper"
export PYAPP_PROJECT_PATH="$(pwd)/$wheel"
export PYAPP_EXEC_SPEC="anki_image_updater:start_app"
export PYAPP_PYTHON_VERSION="3.12"
export PYAPP_FULL_ISOLATION="true"
# Fetch pip lazily at first run; keeps the exe smaller.
export PYAPP_PIP_EXTERNAL="true"

cargo install pyapp --force --root dist-bin

# Determine final binary name based on OS / arch.
uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "$uname_s" in
    Darwin)
        suffix=""
        case "$uname_m" in
            arm64)  os_arch="macos-arm64" ;;
            x86_64) os_arch="macos-x64"  ;;
            *)      os_arch="macos-$uname_m" ;;
        esac
        ;;
    Linux)
        suffix=""
        os_arch="linux-$uname_m"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        suffix=".exe"
        os_arch="windows-x64"
        ;;
    *)
        suffix=""
        os_arch="$(echo "$uname_s" | tr '[:upper:]' '[:lower:]')-$uname_m"
        ;;
esac

src="dist-bin/bin/pyapp$suffix"
dst="dist-bin/bin/AnkiImageUpdater-$os_arch$suffix"
mv "$src" "$dst"

echo ">> Done."
ls -lh "$dst"
