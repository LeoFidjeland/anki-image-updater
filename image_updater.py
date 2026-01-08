import requests
import json
import base64
import os
import time
import argparse
import re
import logging
from dotenv import load_dotenv
from nicegui import ui, app

# Load environment variables
load_dotenv()

# ================= CONFIGURATION DEFAULTS =================
DEFAULT_DECK_NAME = "The Heart of Tibetan Language -  V1"
DEFAULT_FIELD_SEARCH = "English"
DEFAULT_FIELD_IMAGE = "Image"
DEFAULT_FIELD_SOURCE = "Image Source"
DEFAULT_FIELD_NOTES = "Notes"
DEFAULT_IMAGES_PER_TERM = 5
DEFAULT_TAG = "pexels-updated"
DEFAULT_TAG_SKIPPED = "skipped-pexels"
ANKI_URL = "http://localhost:8765"
# ==========================================================

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("anki_updater.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "YOUR_PEXELS_API_KEY_HERE")

def anki_invoke(action, params=None):
    """Helper to communicate with AnkiConnect."""
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    
    try:
        response = requests.post(ANKI_URL, json=payload).json()
        if len(response) != 2:
            raise Exception("Response has an unexpected number of fields")
        if "error" not in response:
            raise Exception("Response is missing required error field")
        if response["error"] is not None:
            raise Exception(response["error"])
        return response["result"]
    except Exception as e:
        logger.error(f"Error invoking Anki method '{action}': {e}")
        return None

def validate_api_key(api_key):
    """Checks if the API key is set."""
    if not api_key or "YOUR_PEXELS" in api_key:
        print("❌ ERROR: Pexels API Key is required.")
        return False
    return True

def search_pexels(query, api_key, count=1):
    """Searches Pexels. Returns list of dicts: {'thumb': url, 'full': url}."""
    if not api_key or "YOUR_PEXELS" in api_key:
        return []

    headers = {'Authorization': api_key}
    url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}"
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        results = []
        if data['photos']:
            for photo in data['photos']:
                results.append({
                    'thumb': photo['src']['medium'],
                    'full': photo['src']['original'],  # Full resolution
                    'context_url': photo['url'] # Pexels page URL
                })
        return results
    except Exception as e:
        logger.warning(f"Error searching Pexels for '{query}': {e}")
    return []

def download_image_as_base64(url):
    """Downloads an image URL and converts it to base64 for Anki."""
    try:
        r = requests.get(url)
        r.raise_for_status()
        return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None

def get_anki_image_base64(filename):
    """Retrieves an image from Anki media collection as base64."""
    try:
        data = anki_invoke("retrieveMediaFile", {"filename": filename})
        if data:
            return data
    except Exception as e:
        logger.error(f"Failed to retrieve media file '{filename}': {e}")
    return None

class CardManager:
    def __init__(self, args):
        self.args = args
        self.note_ids = []
        self.current_index = -1
        self.current_note = None
        self.current_term = ""
        self.current_old_image_b64 = None
        
        self.status_label = None
        self.main_container = None
    
    def load_cards(self):
        logger.info(f"Scanning deck: {self.args.deck}")
        try:
            self.note_ids = anki_invoke("findNotes", {"query": f'deck:"{self.args.deck}"'})
            if not self.note_ids:
                ui.notify(f"No cards found in deck '{self.args.deck}'", type='warning')
                return
            ui.notify(f"Found {len(self.note_ids)} cards.", type='positive')
            self.next_card()
        except:
            ui.notify("Error connecting to Anki. Is it running?", type='negative')

    def next_card(self):
        self.current_index += 1
        if self.current_index >= len(self.note_ids):
            ui.notify("All cards processed!", type='positive')
            if self.status_label: self.status_label.set_text("All Done! Check the Anki Browser.")
            if self.main_container: self.main_container.clear()
            return

        note_id = self.note_ids[self.current_index]
        notes_info = anki_invoke("notesInfo", {"notes": [note_id]})
        if not notes_info:
            self.next_card()
            return

        self.current_note = notes_info[0]
        fields = self.current_note['fields']
        raw_term = fields.get(self.args.field_term, {}).get('value', '')
        self.current_term = raw_term.split('<')[0].strip()
        
        # Extract old image filename if present
        # Looks like: <img src="paste-123.jpg">
        self.current_old_image_b64 = None
        old_img_html = fields.get(self.args.field_image, {}).get('value', '')
        match = re.search(r'src="([^"]+)"', old_img_html)
        if match:
            filename = match.group(1)
            b64_data = get_anki_image_base64(filename)
            if b64_data:
                self.current_old_image_b64 = f"data:image/jpeg;base64,{b64_data}"

        if not self.current_term:
            logger.warning(f"Skipping empty term for ID {note_id}")
            self.next_card()
            return

        self.update_ui()

    def update_ui(self):
        if self.status_label:
            self.status_label.set_text(f"Card {self.current_index + 1}/{len(self.note_ids)}: {self.current_term}")
        
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                # Layout: Split into "Current" (Left) and "New" (Right/Grid)
                with ui.row().classes('w-full gap-4'):
                    
                    # --- Left: Old Image ---
                    with ui.card().classes('w-1/4 min-w-[200px] p-2 bg-gray-50'):
                        ui.label("Current Image").classes('text-sm font-bold text-gray-500 mb-2')
                        if self.current_old_image_b64:
                            ui.image(self.current_old_image_b64).classes('w-full rounded')
                        else:
                            ui.label("No Image").classes('text-gray-400 italic text-center py-10')

                    # --- Right: New Options ---
                    with ui.column().classes('flex-1'):
                        ui.label(f"Search Results for '{self.current_term}'").classes('text-lg font-semibold mb-2')
                        
                        # Container for async results
                        results_container = ui.column().classes('w-full')
                        
                        with results_container:
                            ui.label("Loading from Pexels...").classes('animate-pulse text-blue-500')

                            def fetch_and_show():
                                results_container.clear()
                                with results_container:
                                    images = search_pexels(self.current_term, PEXELS_API_KEY, count=self.args.count)
                                    if not images:
                                        ui.label("No results found.").classes('text-red-500')
                                        return
                                    
                                    with ui.grid(columns=3).classes('w-full gap-4'):
                                        for img in images:
                                            with ui.card().classes('cursor-pointer hover:ring-4 hover:ring-green-400 transition-all p-0') as card:
                                                ui.image(img['thumb']).classes('h-48 w-full object-cover')
                                                # Pass FULL resolution URL to select
                                                card.on('click', lambda _, i=img: self.select_image(i))
                            
                            ui.timer(0.1, fetch_and_show, once=True)

    def select_image(self, img_data):
        """
        img_data is {'thumb': ..., 'full': ..., 'context_url': ...}
        """
        url = img_data['full']
        ui.notify("Downloading full resolution...", type='info')
        
        # 1. Download
        image_b64 = download_image_as_base64(url)
        if not image_b64:
            ui.notify("Failed to download image", type='negative')
            return

        # 2. Prepare Filename
        clean_term = self.current_term
        safe_filename_base = re.sub(r'[^a-zA-Z0-9]', '_', clean_term).strip('_')
        timestamp = int(time.time())
        filename = f"pexels_{safe_filename_base}_{timestamp}.jpg"

        # 3. Store Media
        anki_invoke("storeMediaFile", {
            "filename": filename,
            "data": image_b64
        })

        # 4. Update Fields
        fields = self.current_note['fields']
        current_notes = fields.get(self.args.field_notes, {}).get('value', '')

        # Construct new field values
        # REQUIREMENT: Save only the url ... no html wrapper
        # REQUIREMENT: source link goes to a site where we can watch the image in its context
        new_source_content = img_data['context_url']
        
        # REQUIREMENT: remove the old image once a new one is selected, don't move it
        # So we just ignore the old image content completely.
        new_image_content = f'<img src="{filename}">'
        
        # Notes remain as they were (append nothing)
        new_notes_content = current_notes

        update_payload = {
            "note": {
                "id": self.current_note['noteId'],
                "fields": {
                    self.args.field_image: new_image_content,
                    self.args.field_source: new_source_content,
                    self.args.field_notes: new_notes_content
                }
            }
        }
        
        anki_invoke("updateNoteFields", update_payload)
        anki_invoke("addTags", {"notes": [self.current_note['noteId']], "tags": self.args.tag})

        ui.notify(f"Updated '{clean_term}'!", type='positive')
        self.next_card()

    def skip_card(self):
        # REQUIREMENT: tax the skipped cards (tag)
        anki_invoke("addTags", {"notes": [self.current_note['noteId']], "tags": DEFAULT_TAG_SKIPPED})
        ui.notify(f"Skipped and tagged '{self.current_term}'", type='warning')
        self.next_card()


def main():
    parser = argparse.ArgumentParser(description="Anki Image Fetcher GUI")
    parser.add_argument("--deck", default=DEFAULT_DECK_NAME)
    parser.add_argument("--field-term", default=DEFAULT_FIELD_SEARCH)
    parser.add_argument("--field-image", default=DEFAULT_FIELD_IMAGE)
    parser.add_argument("--field-source", default=DEFAULT_FIELD_SOURCE)
    parser.add_argument("--field-notes", default=DEFAULT_FIELD_NOTES)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--count", type=int, default=DEFAULT_IMAGES_PER_TERM)
    
    args = parser.parse_args()
    
    if not validate_api_key(PEXELS_API_KEY):
        return

    manager = CardManager(args)

    # --- UI LAYOUT ---
    with ui.column().classes('w-full max-w-6xl mx-auto p-4'):
        # Header
        with ui.row().classes('w-full justify-between items-center mb-4'):
            ui.label("Anki Image Selector (High-Res)").classes('text-2xl font-bold')
            manager.status_label = ui.label("Ready to start...").classes('text-xl text-blue-600 font-semibold')
        
        # Main Area
        manager.main_container = ui.column().classes('w-full min-h-[500px] border border-gray-200 rounded-lg p-4 bg-white shadow-sm')
        
        # Footer Controls
        with ui.row().classes('w-full justify-end mt-4 gap-4'):
            ui.button("Start / Load Cards", on_click=manager.load_cards).classes('bg-green-600')
            ui.button("Skip Card", on_click=manager.skip_card).classes('bg-gray-500')

    ui.run(title="Anki Image Updater", reload=False, dark=False)

if __name__ == "__main__":
    main()