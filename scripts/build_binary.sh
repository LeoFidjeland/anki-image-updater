#!/usr/bin/env bash
# Build a single-file PyApp binary from the current source.
#
# Requires:
#   - uv  (https://docs.astral.sh/uv/)
#   - cargo / rustc  (e.g. `brew install rust` on macOS)
#
# Output:
#   macOS: dist-bin/AnkiImageUpdater-<arch>.zip containing Anki Image Updater.app
#   Windows (Git Bash): dist-bin/AnkiImageUpdater-windows-x64.exe (single self-contained launcher; embeds PyApp)
#   Linux: dist-bin/bin/AnkiImageUpdater-linux-<arch> (raw PyApp binary only)

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

if [[ "$uname_s" == MINGW* || "$uname_s" == MSYS* || "$uname_s" == CYGWIN* ]]; then
    echo ">> Renaming PyApp payload"
    mv dist-bin/bin/pyapp.exe dist-bin/bin/AnkiImageUpdaterPyApp.exe
    echo ">> Publishing single-file WinForms launcher (.NET 8; requires dotnet SDK 8+)"
    emb="packaging/windows/launcher/Embedded"
    mkdir -p "$emb"
    cp dist-bin/bin/AnkiImageUpdaterPyApp.exe "$emb/"
    pub="dist-bin/winpublish"
    rm -rf "$pub"
    dotnet publish packaging/windows/launcher/AnkiImageUpdater.Launcher.csproj \
        -c Release -o "$pub" \
        -p:PublishProfile=WinX64SelfContained \
        -p:SelfContained=true
    out_exe="dist-bin/AnkiImageUpdater-windows-x64.exe"
    cp "$pub/AnkiImageUpdater.exe" "$out_exe"
    # .NET 8 RID-only publish defaults to FDD (~9 MB). Self-contained + PyApp should be much larger.
    sz=$(wc -c <"$out_exe" | tr -d ' ')
    min=$((35 * 1024 * 1024))
    if [ "$sz" -lt "$min" ]; then
        echo ">> ERROR: $out_exe is only $sz bytes (expected >= $min). Publish is probably framework-dependent — use PublishProfile=WinX64SelfContained." >&2
        exit 1
    fi
    echo ">> Done. Optional: rcedit \"$out_exe\" --set-icon packaging/windows/AppIcon.ico"
    ls -lh "$out_exe"
elif [[ "$uname_s" == "Darwin" ]]; then
    dst="dist-bin/bin/AnkiImageUpdater-$os_arch"
    mv dist-bin/bin/pyapp "$dst"
    echo ">> Packaging macOS .app"
    ./scripts/package_macos_app.sh "$dst" "dist-bin/AnkiImageUpdater-$os_arch.zip"
else
    dst="dist-bin/bin/AnkiImageUpdater-$os_arch$suffix"
    mv dist-bin/bin/pyapp$suffix "$dst"
    echo ">> Done."
    ls -lh "$dst"
fi
