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
3. **Windows**: Run **`AnkiImageUpdater-windows-x64.exe`** (double-click or place it anywhere you like). The download is one file; on first launch it unpacks the Python runtime bootstrapper under `%LOCALAPPDATA%\anki-image-updater\pyapp\`. The file is larger than a typical small app because it includes a **self-contained .NET 8** runtime plus the embedded payload.
4. Make sure Anki is running.

### First launch takes a little while

The **macOS** and **Windows** launchers both show a small **“Preparing the app…”** window with a progress bar while the runtime sets things up (downloading Python on first run, creating a virtual environment, installing dependencies). That window **hides by itself** once the UI is available at `http://localhost:8080`. Your browser should open automatically shortly after. Later launches are much faster.

The Windows launcher is a **.NET 8** WinForms app published as a **single self-contained** executable, so recipients do **not** need to install the .NET runtime separately.

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
- **Windows**: `%LOCALAPPDATA%\pyapp\anki-image-updater` (Python / venv cache) and `%LOCALAPPDATA%\anki-image-updater\pyapp\` (extracted PyApp bootstrapper from the launcher)

## Troubleshooting
- **Crashes or won’t start on a friend’s Mac (including macOS 15 / Sequoia)**: The OS version is rarely the cause by itself. Check these first:
    - **CPU architecture**: Apple Silicon (M1/M2/…) needs **`AnkiImageUpdater-macos-arm64.zip`**. Intel Macs need **`AnkiImageUpdater-macos-intel.zip`**. The wrong one will fail immediately (often with *“bad CPU type”* if you run the inner binary from Terminal).
    - **Gatekeeper / quarantine**: Still use **Open Anyway** in **System Settings → Privacy & Security**, or `xattr -cr` on the `.app`, then try again.
    - **See the real error**: Open **Terminal** and run  
      `"$HOME/Downloads/Anki Image Updater.app/Contents/MacOS/AnkiImageUpdaterPyApp"`  
      (adjust the path). Copy anything printed there or send a **Crash Report** from **Console.app** → Crash Reports → *Anki Image Updater*.
- **macOS says the app is “damaged”**: Usually still **Gatekeeper + quarantine**, not file corruption. Try **System Settings → Privacy & Security → Open Anyway**, or `xattr -cr "/path/to/Anki Image Updater.app"`, or right-click → **Open**. Diagnostics: `spctl --assess --verbose "/path/to/Anki Image Updater.app"`. The real PyApp payload is `Contents/MacOS/AnkiImageUpdaterPyApp` if you need to run it from Terminal for debugging.
- **App doesn't connect to Anki**: Ensure Anki is running and AnkiConnect is configured to allow `localhost`.
- **Browser doesn't open**: Navigate manually to `http://localhost:8080`.
- **Windows: “This app can’t run on your PC”**: You need **64-bit Windows** and a build marked **x64**. Re-download the release asset if the file was truncated. Antivirus quarantine can also block self-extracting single-file apps — check Windows Security → Protection history.
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

On **Windows**, CI builds a **WinForms launcher** ([`packaging/windows/launcher`](packaging/windows/launcher)) as **`PublishSingleFile`** + **`SelfContained`** for **win-x64**. The PyApp binary is copied into `packaging/windows/launcher/Embedded/` before `dotnet publish` and stored as an **embedded resource**; at runtime it is written to `%LOCALAPPDATA%\anki-image-updater\pyapp\` when needed. The release artifact is **`AnkiImageUpdater-windows-x64.exe`**; CI sets the icon with [rcedit](https://github.com/electron/rcedit).

The build runs `uv build --wheel`, then `cargo install pyapp` to embed that wheel in a small Rust bootstrapper. On first launch, PyApp downloads [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (the same family of runtimes `uv` uses), creates a per-app virtual environment, and runs the entry point.

### App icons (macOS + Windows)

Source artwork lives at **`packaging/macos/anki-image-updater-icon.png`** (square PNG).

**Design tip (macOS “double frame” / weird outer shadow):** Use a **flat square** master (e.g. 1024×1024). Let the **system** apply the rounded squircle — do **not** bake in a white “app icon plate,” inner rounded rectangle, or drop shadow in the PNG. Those effects are for *preview mockups*; in a real `.icns`, macOS adds its own mask and depth, so mockup chrome looks like an extra border and a second shadow. Keep important detail inside the central ~90% ([icon grid](https://developer.apple.com/design/human-interface-guidelines/app-icons)), but fill the canvas with your illustration (sky, edges, etc.), not a fake icon frame.

**macOS:** regenerate **`packaging/macos/AppIcon.icns`** on a Mac (then commit it):

```bash
./scripts/generate_macos_icon.sh
```

You can pass another PNG path as the first argument.

**Windows:** regenerate **`packaging/windows/AppIcon.ico`** (then commit it):

```bash
uv run --with pillow python scripts/generate_windows_icon.py
```

When the PNG changes, run **both** generators and commit the updated `.icns`, `.ico`, and `.png`.

### Release a new version

1. Bump `version` in [`pyproject.toml`](./pyproject.toml).
2. Commit and tag: `git tag v1.0.1 && git push origin main && git push origin v1.0.1`.
3. GitHub Actions builds macOS (`.app` in a zip) and Windows (`.exe`) and attaches them to the release.
