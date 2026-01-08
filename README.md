# Anki Image Updater

A graphical tool to help you find and update images for your Anki cards using Pexels, Unsplash, and Freepik.

## Features
- **Smart Filtering**: Automatically finds cards that need images (missing or placeholders).
- **Multiple Providers**: Search images from Pexels, Unsplash, and Freepik.
- **One-Click Update**: Select an image to automatically download it, update the card, and format the fields.
- **Safety**: Skips cards that already have manually added sources.
- **Standalone App**: Can be built into a standalone executable for macOS.

## Prerequisites
- **Anki** must be running with the **AnkiConnect** add-on installed.
- Python 3.10+ (if running from source).

## Installation

1. Clone the repository or download the source code.
2. (Optional) Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configuration:
   - The app looks for an `.env` file for API keys, OR uses the keys hardcoded in the script (for distributed builds).
   - If running locally, create a `.env` file with:
     ```
     PEXELS_KEY=your_key
     UNSPLASH_KEY=your_key
     FREEPIK_KEY=your_key
     ```

## Usage

### Running from Source
```bash
python3 image_updater.py
```
This will launch a terminal window and automatically open your default browser to the application interface.

### Running the App (Standalone)
Double-click the `Anki Image Updater` executable in the `dist` folder.
- A terminal window will open first (to show logs/status).
- The browser tab will open automatically.
- **To Exit**: Close the browser tab (wait 4s for auto-shutdown) or simply close the terminal window.

## Building the App
To create a standalone application bundle:

1. Ensure `pyinstaller` is installed (`pip install pyinstaller`).
2. Run the build script:
   ```bash
   ./build_app.sh
   ```
3. The output will be in the `dist/Anki Image Updater` directory.

## Troubleshooting
- **App doesn't connect to Anki**: Ensure Anki is running and AnkiConnect is configured to allow `localhost`.
- **Browser doesn't open**: You can manually navigate to `http://localhost:8080`.
- **Permissions**: On macOS, you might need to allow the application to run via System Settings > Security & Privacy if it's not signed.
