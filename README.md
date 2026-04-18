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

### First launch takes a little while

The Mac app includes a small **“Preparing the app…”** window with a progress bar while the embedded runtime sets things up (downloading Python on first run, creating a virtual environment, installing dependencies). That window **closes by itself** once the UI is available at `http://localhost:8080`. Your browser should open automatically shortly after. Later launches are much faster.

### Bypass the operating system's "untrusted file" warning

The app is **ad hoc code-signed** (not an Apple Developer ID certificate), so Gatekeeper still treats it as untrusted until you approve it once. **We cannot change Apple’s exact wording** — only a paid [Apple Developer Program](https://developer.apple.com/programs/) account plus **notarization** removes these prompts entirely.

**macOS** usually shows *“cannot be opened because the developer cannot be verified”* (or similar). After you try to open the app once, you can also approve it without Terminal:

1. Open **System Settings → Privacy & Security**.
2. Scroll to **Security** and click **Open Anyway** next to the message about *Anki Image Updater*.

You can still use any of these if you prefer:

- Right-click (or Ctrl-click) **`Anki Image Updater.app`** → **Open** → **Open** in the dialog.
- Terminal (clears quarantine): `xattr -cr "/path/to/Anki Image Updater.app"`

**Windows**: SmartScreen will say *"Windows protected your PC"*.
- Click **More info** → **Run anyway**.

### Configuration
On first run the app asks for API keys (Pexels, Unsplash, Freepik, Pixabay). Wikimedia Commons does not require a key. Settings are saved to your user config directory.

### Uninstall
Delete the app (and the downloaded zip / installer) and the runtime cache:
- **macOS**: `~/Library/Application Support/pyapp/anki-image-updater`
- **Windows**: `%LOCALAPPDATA%\pyapp\anki-image-updater`

## Troubleshooting
- **macOS says the app is “damaged”**: Usually still **Gatekeeper + quarantine**, not file corruption. Try **System Settings → Privacy & Security → Open Anyway**, or `xattr -cr "/path/to/Anki Image Updater.app"`, or right-click → **Open**. Diagnostics: `spctl --assess --verbose "/path/to/Anki Image Updater.app"`. The real PyApp payload is `Contents/MacOS/AnkiImageUpdaterPyApp` if you need to run it from Terminal for debugging.
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

On **macOS** this also produces `dist-bin/AnkiImageUpdater-<arch>.zip`, which contains **`Anki Image Updater.app`**. The app bundle is built by [`scripts/package_macos_app.sh`](scripts/package_macos_app.sh): a thin **Swift** launcher ([`packaging/macos/launcher/main.swift`](packaging/macos/launcher/main.swift)) provides a preparation window, then runs the **PyApp** binary as `Contents/MacOS/AnkiImageUpdaterPyApp`. The bundle is **ad hoc signed** (`codesign -s -`) before zipping.

On **Windows** the output is `dist-bin/bin/AnkiImageUpdater-windows-x64.exe`.

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
