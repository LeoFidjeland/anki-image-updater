# Anki Image Updater

A graphical tool to help you find and update images for your Anki cards using Pexels, Unsplash, and Freepik.

## Features
- **Smart Filtering**: Automatically finds cards that need images (missing or placeholders).
- **Multiple Providers**: Search images from Pexels, Unsplash, and Freepik.
- **One-Click Update**: Select an image to automatically download it, update the card, and format the fields.
- **Safety**: Skips cards that already have manually added sources.

## Prerequisites
- **Anki** must be running with the **AnkiConnect** add-on installed.
- **Python 3.9+**

## Installation

The easiest way to install and run the application globally is using [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/LeoFidjeland/anki-image-updater
```

Once installed, you can start the application from your terminal:

```bash
anki-image-updater
```

*(To remove the application later, simply run `uv tool uninstall anki-image-updater`)*

A browser window will open automatically. Wait 4 seconds after closing the tab for the tool to auto-shutdown, or press `Ctrl+C` in your terminal.

## Development

If you want to contribute or modify the application, use `uv` to manage the project locally:

1. Clone the repository:
   ```bash
   git clone https://github.com/LeoFidjeland/anki-image-updater.git
   cd anki-image-updater
   ```
2. Run the application (this automatically creates an isolated virtual environment and installs dependencies):
   ```bash
   uv run anki-image-updater
   ```
   *(Alternatively, you can run `uv run python anki_image_updater.py`)*

### Configuration
The app will prompt you for API keys (Pexels, Unsplash, Freepik) upon first launch. Settings are securely saved to your user configuration directory.

### Running Tests
To run the project's test suite, execute:
```bash
uv run pytest
```

## Troubleshooting
- **App doesn't connect to Anki**: Ensure Anki is running and AnkiConnect is configured to allow `localhost`.
- **Browser doesn't open**: You can manually navigate to `http://localhost:8080`.
- **Permissions**: On macOS, you might need to allow the application to run via System Settings > Security & Privacy if it's not signed.
