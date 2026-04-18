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
    - **macOS (Apple Silicon)**: `AnkiImageUpdater-macos-arm64`
    - **Windows (64-bit)**: `AnkiImageUpdater-windows-x64.exe`
2. Make sure Anki is running.
3. Double-click the downloaded file.

### First launch takes 10–30 seconds

On first launch the app downloads a private Python runtime (~30 MB) into a cache directory. You will see a terminal window briefly. Subsequent launches start in under a second.

### Bypass the operating system's "untrusted file" warning

The binaries are not code-signed (yet), so your OS will warn you the first time:

**macOS**: Finder will say *"cannot be opened because it is from an unidentified developer"*.
- Right-click (or Ctrl-click) the file → **Open** → **Open** in the dialog. You only need to do this once.
- Alternatively, from Terminal: `xattr -d com.apple.quarantine ~/Downloads/AnkiImageUpdater-macos-arm64`, then double-click normally.

**Windows**: SmartScreen will say *"Windows protected your PC"*.
- Click **More info** → **Run anyway**.

### Configuration
On first run the app asks for API keys (Pexels, Unsplash, Freepik, Pixabay). Wikimedia Commons does not require a key. Settings are saved to your user config directory.

### Uninstall
Delete the downloaded binary and the app's cache directory:
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

### Build a single-file binary locally

Requires [`uv`](https://docs.astral.sh/uv/) plus a Rust toolchain (`brew install rust` on macOS, or `rustup` on Windows/Linux).

```bash
./scripts/build_binary.sh
```

Output lands at `dist-bin/bin/AnkiImageUpdater-<os>-<arch>[.exe]`. The build does two steps: `uv build --wheel` to produce a standard Python wheel, then `cargo install pyapp` to embed that wheel into a small Rust bootstrapper. The bootstrapper downloads [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (the same distribution `uv` itself uses) on the user's first launch, creates a per-app venv, and runs the entry point.

### Release a new version

1. Bump `version` in [`pyproject.toml`](./pyproject.toml).
2. Commit and tag: `git tag v0.2.0 && git push --tags`.
3. GitHub Actions builds macOS and Windows binaries and attaches them to the release.
