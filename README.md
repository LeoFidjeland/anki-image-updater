# Anki Image Updater

A graphical tool to help you find and update images for your Anki cards using Pexels, Unsplash, Freepik, Pixabay, and Wikimedia Commons.

## Features
- **Smart Filtering**: Automatically finds cards that need images (missing or placeholders).
- **Multiple Providers**: Search images from Pexels, Unsplash, Freepik, Pixabay, and Wikimedia Commons.
- **One-Click Update**: Select an image to automatically download it, update the card, and format the fields.
- **Safety**: Skips cards that already have manually added sources.

## Prerequisites
- **Anki** must be running with the **AnkiConnect** add-on installed.
  - Install AnkiConnect in Anki: `Tools → Add-ons → Get Add-ons…`, paste code `2055492159`, restart Anki.

## Install (for end users)

1. Download the file for your operating system from the [latest release](https://github.com/LeoFidjeland/anki-image-updater/releases/latest):
    - **macOS (Apple Silicon, M1/M2/M3/…)**: `AnkiImageUpdater-macos-arm64.zip`
    - **macOS (Intel)**: `AnkiImageUpdater-macos-intel.zip`
    - **Windows (64-bit)**: `AnkiImageUpdater-windows-x64.exe`
2. **macOS**: Unzip the download. You get **`Anki Image Updater.app`** — a normal Mac application. Drag it to **Applications** (optional), then open it from Finder like any other app.
3. **Windows**: Double-click the `.exe`.
4. Make sure Anki is running.

### First launch takes 10–30 seconds

On first launch the app downloads a private Python runtime (~30 MB) into a cache directory. Your default web browser should open to the tool shortly after. Subsequent launches start in under a second.

### Bypass the operating system's "untrusted file" warning

The binaries are not code-signed (yet), so your OS will warn you the first time:

**macOS**: Finder will say *"cannot be opened because it is from an unidentified developer"*.
- Right-click (or Ctrl-click) **`Anki Image Updater.app`** → **Open** → **Open** in the dialog. You only need to do this once.
- Alternatively, from Terminal:  
  `xattr -dr com.apple.quarantine "/path/to/Anki Image Updater.app"`

**Windows**: SmartScreen will say *"Windows protected your PC"*.
- Click **More info** → **Run anyway**.

### Configuration
On first run the app asks for API keys (Pexels, Unsplash, Freepik, Pixabay). Wikimedia Commons does not require a key. Settings are saved to your user config directory.

### Uninstall
Delete the app (and the downloaded zip / installer) and the runtime cache:
- **macOS**: `~/Library/Application Support/pyapp/anki-image-updater`
- **Windows**: `%LOCALAPPDATA%\pyapp\anki-image-updater`

## Troubleshooting
- **App doesn't connect to Anki**: Ensure Anki is running and AnkiConnect is configured to allow `localhost`.
- **Browser doesn't open**: Navigate manually to `http://localhost:8080`.
- **Log file location**:
  - macOS: `~/Library/Logs/anki-image-updater/anki_image_updater.log`
  - Windows: `%LOCALAPPDATA%\LeoFidjeland\anki-image-updater\Logs\anki_image_updater.log`

## Development

The repo uses [`uv`](https://docs.astral.sh/uv/) for Python dependency management.

### Run from source

```bash
git clone https://github.com/LeoFidjeland/anki-image-updater.git
cd anki-image-updater
uv run anki-image-updater
```

### Run the test suite

```bash
uv run pytest
```

### Build release binaries locally

Requires [`uv`](https://docs.astral.sh/uv/) plus a Rust toolchain (`brew install rust` on macOS, or `rustup` on Windows/Linux).

```bash
./scripts/build_binary.sh
```

On **macOS** this also produces `dist-bin/AnkiImageUpdater-<arch>.zip`, which contains **`Anki Image Updater.app`**. On **Windows** the output is `dist-bin/bin/AnkiImageUpdater-windows-x64.exe`.

The build runs `uv build --wheel`, then `cargo install pyapp` to embed that wheel in a small Rust bootstrapper. On first launch, PyApp downloads [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (the same family of runtimes `uv` uses), creates a per-app virtual environment, and runs the entry point.

### macOS app icon

Source artwork lives at **`packaging/macos/anki-image-updater-icon.png`** (square PNG). The bundled icon is **`packaging/macos/AppIcon.icns`**, which [`scripts/package_macos_app.sh`](scripts/package_macos_app.sh) copies into the `.app` when present.

After editing the PNG, regenerate the `.icns` on a Mac:

```bash
./scripts/generate_macos_icon.sh
```

You can pass another PNG path as the first argument. Commit both the `.png` and the updated `.icns` when the icon changes.

### Release a new version

1. Bump `version` in [`pyproject.toml`](./pyproject.toml).
2. Commit and tag: `git tag v1.0.1 && git push origin main && git push origin v1.0.1`.
3. GitHub Actions builds macOS (`.app` in a zip) and Windows (`.exe`) and attaches them to the release.
