#!/bin/bash

echo "Building Anki Image Updater..."

# Remove previous builds
rm -rf build dist *.spec

# Run PyInstaller
# --name: App name
# --onefile: Single executable
# --windowed: No terminal window
# --add-data: Include NiceGUI assets (crucial!)
# --clean: Clean cache

./venv/bin/pyinstaller \
    --name "Anki Image Updater" \
    --onedir \
    --add-data "$(./venv/bin/python -c 'import nicegui; import os; print(os.path.dirname(nicegui.__file__))'):nicegui" \
    image_updater.py

echo "Build complete! Check the 'dist' folder."
