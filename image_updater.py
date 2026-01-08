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
DEFAULT_IMAGES_PER_TERM = 6
DEFAULT_TAG = "replaced-auto" # Generic tag
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

# KEYS
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
FREEPIK_API_KEY = os.getenv("FREEPIK_API_KEY")

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

def validate_keys():
    """Warns about missing keys."""
    missing = []
    if not PEXELS_API_KEY: missing.append("PEXELS_API_KEY")
    if not UNSPLASH_ACCESS_KEY: missing.append("UNSPLASH_ACCESS_KEY")
    if not FREEPIK_API_KEY: missing.append("FREEPIK_API_KEY")
    
    if len(missing) == 3:
        print("❌ ERROR: No API keys found. Please set at least one in .env")
        return False
    elif missing:
        print(f"⚠️ Warning: Some keys are missing: {', '.join(missing)}")
    return True

# --- SEARCH PROVIDERS ---

def search_pexels(query, count=1, page=1):
    """Searches Pexels."""
    if not PEXELS_API_KEY: return []
    
    headers = {'Authorization': PEXELS_API_KEY}
    url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}&page={page}"
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        results = []
        if data.get('photos'):
            for photo in data['photos']:
                results.append({
                    'thumb': photo['src']['medium'],
                    'full': photo['src']['original'],
                    'context_url': photo['url'],
                    'provider': 'pexels'
                })
        return results
    except Exception as e:
        logger.warning(f"Error searching Pexels for '{query}': {e}")
        return []

def search_unsplash(query, count=1, page=1):
    """Searches Unsplash."""
    if not UNSPLASH_ACCESS_KEY: return []
    
    headers = {'Authorization': f'Client-ID {UNSPLASH_ACCESS_KEY}'}
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page={count}&page={page}"
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        results = []
        if data.get('results'):
            for photo in data['results']:
                results.append({
                    'thumb': photo['urls']['small'],
                    'full': photo['urls']['raw'],
                    'context_url': photo['links']['html'],
                    'provider': 'unsplash'
                })
        return results
    except Exception as e:
        logger.warning(f"Error searching Unsplash for '{query}': {e}")
        return []

def search_freepik(query, count=1, page=1):
    """Searches Freepik."""
    if not FREEPIK_API_KEY: return []
    
    headers = {'x-freepik-api-key': FREEPIK_API_KEY}
    url = f"https://api.freepik.com/v1/resources?term={query}&limit={count}&page={page}"
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        results = []
        if data.get('data'):
            for item in data['data']:
                if 'image' in item and 'source' in item['image']:
                     results.append({
                        'thumb': item['image']['source']['url'],
                        'full': item['image']['source']['url'],
                        'context_url': item.get('url', '#'),
                        'provider': 'freepik'
                    })
        return results
    except Exception as e:
        logger.warning(f"Error searching Freepik for '{query}': {e}")
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

def notify(msg, type='info'):
    """Wrapper for ui.notify with standard position."""
    ui.notify(msg, type=type, position='bottom-left')

class CardManager:
    def __init__(self, args):
        self.args = args
        self.note_ids = []
        self.current_index = -1
        self.current_note = None
        self.current_term = ""
        self.current_old_image_b64 = None
        
        # State
        self.current_provider = 'pexels'
        self.current_page = 1
        self.loaded_images = []
        
        # UI Elements
        self.status_label = None
        self.main_container = None
        self.results_area = None
    
    def fetch_decks(self):
        return anki_invoke("deckNames") or []

    def start_deck_load(self, deck_name):
        self.args.deck = deck_name
        self.load_cards()

    def load_cards(self):
        logger.info(f"Scanning deck: {self.args.deck}")
        try:
            # We fetch ALL cards, then filter manually
            # We also exclude cards that are already tagged as auto-skipped
            query = f'deck:"{self.args.deck}" -tag:auto-skipped'
            self.note_ids = anki_invoke("findNotes", {"query": query})
            
            if not self.note_ids:
                notify(f"No cards found (or all skipped/processed) in '{self.args.deck}'", type='warning')
                return
            
            notify(f"Found {len(self.note_ids)} candidates. Filtering...", type='info')
            self.current_index = -1
            self.next_card()
        except Exception as e:
            notify(f"Error: {e}", type='negative')

    def next_card(self):
        self.current_index += 1
        if self.current_index >= len(self.note_ids):
            notify("All cards processed!", type='positive')
            if self.status_label: self.status_label.set_text("All Done!")
            if self.main_container: self.main_container.clear()
            return

        note_id = self.note_ids[self.current_index]
        notes_info = anki_invoke("notesInfo", {"notes": [note_id]})
        if not notes_info:
            self.next_card()
            return

        self.current_note = notes_info[0]
        fields = self.current_note['fields']
        
        # INTELLIGENCE FILTERING
        # 1. Check if Source field is already populated
        source_val = fields.get(self.args.field_source, {}).get('value', '').strip()
        if source_val:
            logger.info(f"Skipping {note_id}: Source already exists.")
            self.next_card()
            return

        raw_term = fields.get(self.args.field_term, {}).get('value', '')
        self.current_term = raw_term.split('<')[0].strip()
        
        # Extract old image
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

        # Reset pagination/images for new card
        self.current_page = 1
        self.loaded_images = []
        self.refresh_ui_content()

    def set_provider(self, provider):
        self.current_provider = provider
        self.current_page = 1 # Reset page on provider switch
        self.loaded_images = []
        notify(f"Switched to {provider.capitalize()}")
        self.refresh_ui_content()

    def load_more_images(self):
        self.current_page += 1
        notify(f"Loading page {self.current_page}...", type='info')
        self.refresh_results(append=True)

    def refresh_ui_content(self):
        """Refreshes the entire card view."""
        if self.status_label:
            count_remaining = len(self.note_ids) - self.current_index
            self.status_label.set_text(f"Processing: {self.current_term} ({count_remaining} left)")
        
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                # Top Controls: Provider Toggle
                with ui.row().classes('w-full justify-center mb-4 gap-2'):
                    ui.label("Provider:").classes('py-2 font-bold text-gray-600')
                    
                    def render_provider_btn(provider_name):
                        is_active = self.current_provider == provider_name
                        if is_active:
                            btn_props = 'color=blue-6 text-color=white unelevated'
                        else:
                            btn_props = 'color=white text-color=grey-9 outline'
                            
                        ui.button(provider_name.capitalize(), 
                                 on_click=lambda: self.set_provider(provider_name)) \
                                 .props(btn_props) \
                                 .classes('px-4 font-bold')

                    render_provider_btn('pexels')
                    render_provider_btn('unsplash')
                    render_provider_btn('freepik')

                # Layout: Split into "Current" (Left) and "New" (Right/Grid)
                with ui.row().classes('w-full gap-4'):
                    
                    # --- Left: Old Image & Context ---
                    with ui.card().classes('w-1/4 min-w-[200px] p-2 bg-gray-50'):
                        # Context Info (Tibetan)
                        # We try to find a field that looks like Tibetan or just the first non-English field
                        # For now, let's explicitly look for 'Tibetan' as requested, or fallback to showing everything relevant
                        tibetan_val = self.current_note['fields'].get('Tibetan', {}).get('value', '')
                        if tibetan_val:
                             ui.label("Tibetan:").classes('text-xs font-bold text-gray-500 mt-2')
                             ui.html(tibetan_val, sanitize=False).classes('text-2xl text-center my-2 text-purple-800')

                        ui.label("Current Image").classes('text-sm font-bold text-gray-500 mb-2')
                        if self.current_old_image_b64:
                            ui.image(self.current_old_image_b64).classes('w-full rounded mb-4')
                        else:
                            ui.label("No Image").classes('text-gray-400 italic text-center py-10 mb-4')
                        
                        

                    # --- Right: New Options ---
                    with ui.column().classes('flex-1'):
                        # Header: Search Input + Skip Button
                        with ui.row().classes('w-full justify-between items-center mb-2'):
                            
                            def on_search_change(e):
                                self.current_term = e.value
                                # Reset pagination
                                self.current_page = 1
                                self.loaded_images = []
                                self.refresh_results()

                            ui.input(label="Search Query", value=self.current_term) \
                                .on('keydown.enter', lambda e: on_search_change(e.sender)) \
                                .props('outlined dense') \
                                .classes('w-2/3')
                            
                            ui.button("Skip Card", on_click=self.skip_card) \
                                .props('color=grey-5 flat icon=skip_next') \
                                .classes('font-bold')

                        self.results_area = ui.column().classes('w-full')
                        self.refresh_results() # Initial load

    def refresh_results(self, append=False):
        """Refreshes just the search results grid."""
        if not self.results_area: return
        
        # If not appending, clear stored images (logic handled in callers usually, but double check)
        if not append:
            self.loaded_images = []
            self.results_area.clear()
        
        with self.results_area:
            if not self.loaded_images and not append:
                ui.label(f"Loading from {self.current_provider.capitalize()}...").classes('animate-pulse text-blue-500')

            def fetch_and_show():
                # If appending, we are running inside the existing results_area context?
                # Actually NiceGUI builders append to the CURRENT context.
                # So we verify we are in the right place.
                
                new_images = []
                if self.current_provider == 'pexels':
                    new_images = search_pexels(self.current_term, count=self.args.count, page=self.current_page)
                elif self.current_provider == 'unsplash':
                    new_images = search_unsplash(self.current_term, count=self.args.count, page=self.current_page)
                elif self.current_provider == 'freepik':
                    new_images = search_freepik(self.current_term, count=self.args.count, page=self.current_page)

                if not new_images:
                    notify(f"No more results on {self.current_provider.capitalize()}.", type='warning')
                    return

                self.loaded_images.extend(new_images)
                
                # We need to rebuild the grid or append to it. Rebuilding is safer for layout.
                self.results_area.clear()
                with self.results_area:
                    with ui.grid(columns=3).classes('w-full gap-4'):
                        for img in self.loaded_images:
                            with ui.card().classes('cursor-pointer hover:ring-4 hover:ring-green-400 transition-all p-0') as card:
                                ui.image(img['thumb']).classes('h-48 w-full object-cover')
                                card.on('click', lambda _, i=img: self.select_image(i))
                    
                    # Load More Button
                    ui.button("Load More Results", on_click=self.load_more_images) \
                        .classes('w-full mt-4 bg-gray-200 text-gray-800 hover:bg-gray-300')

            # Run async refetch
            ui.timer(0.1, fetch_and_show, once=True)

    def select_image(self, img_data):
        url = img_data['full']
        provider = img_data['provider']
        notify(f"Downloading from {provider}...", type='info')
        
        image_b64 = download_image_as_base64(url)
        if not image_b64:
            notify("Failed to download image", type='negative')
            return

        clean_term = self.current_term
        # Sanitize filenames a bit more strictly
        safe_term = re.sub(r'[^a-zA-Z0-9]', '', clean_term)[:20] 
        timestamp = int(time.time())
        filename = f"{provider}_{safe_term}_{timestamp}.jpg"

        anki_invoke("storeMediaFile", {
            "filename": filename,
            "data": image_b64
        })

        new_source_content = img_data['context_url']
        new_image_content = f'<img src="{filename}">'

        update_payload = {
            "note": {
                "id": self.current_note['noteId'],
                "fields": {
                    self.args.field_image: new_image_content,
                    self.args.field_source: new_source_content,
                }
            }
        }
        
        anki_invoke("updateNoteFields", update_payload)
        
        # AUTO-REPLACED TAG
        tags_to_add = ["auto-replaced", f"updated-{provider}"]
        anki_invoke("addTags", {"notes": [self.current_note['noteId']], "tags": " ".join(tags_to_add)})

        notify(f"Updated '{clean_term}'!", type='positive')
        self.next_card()

    def skip_card(self):
        # AUTO-SKIPPED TAG
        tag = "auto-skipped"
        anki_invoke("addTags", {"notes": [self.current_note['noteId']], "tags": tag})
        notify(f"Skipped '{self.current_term}'", type='warning')
        self.next_card()


def main():
    parser = argparse.ArgumentParser(description="Anki Image Fetcher GUI")
    # Deck is now optional/selectable
    parser.add_argument("--deck", default=None)
    parser.add_argument("--field-term", default=DEFAULT_FIELD_SEARCH)
    parser.add_argument("--field-image", default=DEFAULT_FIELD_IMAGE)
    parser.add_argument("--field-source", default=DEFAULT_FIELD_SOURCE)
    parser.add_argument("--field-notes", default=DEFAULT_FIELD_NOTES)
    parser.add_argument("--count", type=int, default=DEFAULT_IMAGES_PER_TERM)
    
    args = parser.parse_args()
    
    if not validate_keys():
        return

    manager = CardManager(args)

    # --- UI LAYOUT ---
    with ui.column().classes('w-full max-w-6xl mx-auto p-4'):
        # Header
        with ui.row().classes('w-full justify-between items-center mb-4'):
            ui.label("Anki Image Updater").classes('text-2xl font-bold')
            manager.status_label = ui.label("Ready to start...").classes('text-xl text-blue-600 font-semibold')
        
        # Main Area
        manager.main_container = ui.column().classes('w-full min-h-[500px] border border-gray-200 rounded-lg p-4 bg-white shadow-sm')
        
        # Footer Controls
        with ui.row().classes('w-full justify-end mt-4 gap-4'):
             # If no deck provided, we just start by showing deck selector (logic handled inside)
             # But buttons are global. We'll update them dynamically or just have them constantly.
             pass # Controls are now dynamic or inside main_container for the flow
        
        # Initialize
        if args.deck:
            # If deck was passed via CLI, start immediately
            with manager.main_container:
                 ui.button("Start Processing", on_click=lambda: manager.load_cards()).classes('bg-green-600')
        else:
            # Show Deck Selector
            with manager.main_container:
                ui.label("Select a Deck to Begin:").classes('text-lg mb-2')
                decks = manager.fetch_decks()
                if decks:
                    select = ui.select(decks, label="Deck").classes('w-1/2')
                    ui.button("Start", on_click=lambda: manager.start_deck_load(select.value)).classes('bg-blue-600 mt-4')
                else:
                    ui.label("Could not fetch decks. Is Anki running?").classes('text-red-500')
        
        # Global Footer for Skip (only visible when processing effectively)
        # We can re-inject this button in load_cards or leave it here but disable it?
        # Simpler: Clear main_container content and inject appropriate views.
        # So "Skip" should be injected by update_ui/load_cards, not static here.

    ui.run(title="Anki Image Updater", reload=False, dark=False)

if __name__ == "__main__":
    main()