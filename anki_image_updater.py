import sys
import os
import argparse
import logging

# PyInstaller Fix: nicegui assets
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

from nicegui import ui, app, client

from config_manager import ConfigManager
from anki_client import AnkiClient
from search_providers import ImageSearcher
from core import CardManagerLogic, ActionError

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("anki_image_updater.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def notify(msg, type='info'):
    ui.notify(msg, type=type, position='bottom-left')

class AppUI:
    def __init__(self, logic: CardManagerLogic, searcher: ImageSearcher, args):
        self.logic = logic
        self.searcher = searcher
        self.args = args
        
        # UI State
        self.current_provider = 'pexels'
        self.current_page = 1
        self.loaded_images = []
        
        # UI Elements
        self.status_label = None
        self.main_container = None
        self.results_area = None

    def start_deck_load(self, deck_name):
        self.args.deck = deck_name
        self.load_cards()

    def load_cards(self):
        success, message = self.logic.load_deck(self.args.deck)
        if not success:
            notify(message, type='warning')
            return
            
        notify(message, type='info')
        self.next_card()

    def next_card(self):
        found = self.logic.advance_to_next_valid_card()
        if not found:
            notify("All cards processed!", type='positive')
            if self.status_label: self.status_label.set_text("All Done!")
            if self.main_container: self.main_container.clear()
            return
            
        # Reset pagination/images for new card
        self.current_page = 1
        self.loaded_images = []
        self.refresh_ui_content()

    def set_provider(self, provider):
        self.current_provider = provider
        self.current_page = 1
        self.loaded_images = []
        notify(f"Switched to {provider.capitalize()}")
        self.refresh_ui_content()

    def load_more_images(self):
        self.current_page += 1
        notify(f"Loading page {self.current_page}...", type='info')
        self.refresh_results(append=True)

    def select_image(self, img_data):
        provider = img_data['provider']
        notify(f"Downloading from {provider}...", type='info')
        
        try:
            term = self.logic.apply_image_to_card(img_data)
            notify(f"Updated '{term}'!", type='positive')
            self.next_card()
        except ActionError as e:
            notify(str(e), type='negative')
        except Exception as e:
            logger.exception("Error applying image")
            notify(f"Unexpected error: {e}", type='negative')
            
    def skip_card(self):
        term = self.logic.skip_card()
        if term:
            notify(f"Skipped '{term}'", type='warning')
        self.next_card()

    def build_settings_dialog(self):
        with ui.dialog() as settings_dialog, ui.card().classes('w-full max-w-lg'):
            ui.label('Settings').classes('text-xl font-bold mb-4')
            with ui.column().classes('w-full gap-2'):
                ui.label("API Keys").classes('font-bold mt-2')
                pexels_input = ui.input("Pexels API Key", value=self.logic.config.get("PEXELS_API_KEY")).props('type=password')
                unsplash_input = ui.input("Unsplash Access Key", value=self.logic.config.get("UNSPLASH_ACCESS_KEY")).props('type=password')
                freepik_input = ui.input("Freepik API Key", value=self.logic.config.get("FREEPIK_API_KEY")).props('type=password')
                
                ui.label("Defaults").classes('font-bold mt-4')
                deck_input = ui.input("Default Deck Name", value=self.logic.config.get("DEFAULT_DECK_NAME"))
                
                with ui.row().classes('w-full justify-end mt-4'):
                    def save_settings():
                        self.logic.config.set("PEXELS_API_KEY", pexels_input.value.strip())
                        self.logic.config.set("UNSPLASH_ACCESS_KEY", unsplash_input.value.strip())
                        self.logic.config.set("FREEPIK_API_KEY", freepik_input.value.strip())
                        self.logic.config.set("DEFAULT_DECK_NAME", deck_input.value.strip())
                        notify("Settings Saved!", type='positive')
                        settings_dialog.close()
                        
                    ui.button("Cancel", on_click=settings_dialog.close).props('flat')
                    ui.button("Save", on_click=save_settings).classes('bg-blue-600')
        return settings_dialog

    def refresh_ui_content(self):
        if self.status_label:
            count = self.logic.get_remaining_count()
            self.status_label.set_text(f"Processing: {self.logic.current_term} ({count} left)")
            
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                self.build_provider_toggles()
                
                with ui.row().classes('w-full gap-4'):
                    self.build_left_panel()
                    self.build_right_panel()

    def build_provider_toggles(self):
        with ui.row().classes('w-full justify-center mb-4 gap-2'):
            ui.label("Provider:").classes('py-2 font-bold text-gray-600')
            
            def render_provider_btn(provider_name):
                is_active = self.current_provider == provider_name
                btn_props = 'color=blue-6 text-color=white unelevated' if is_active else 'color=white text-color=grey-9 outline'
                ui.button(provider_name.capitalize(), on_click=lambda p=provider_name: self.set_provider(p)) \
                    .props(btn_props).classes('px-4 font-bold')

            render_provider_btn('pexels')
            render_provider_btn('unsplash')
            render_provider_btn('freepik')

    def build_left_panel(self):
        with ui.card().classes('w-1/4 min-w-[200px] p-2 bg-gray-50'):
            # Context Info (Tibetan)
            if self.logic.current_note:
                 tibetan_val = self.logic.current_note['fields'].get('Tibetan', {}).get('value', '')
                 if tibetan_val:
                      ui.label("Tibetan:").classes('text-xs font-bold text-gray-500 mt-2')
                      ui.html(tibetan_val, sanitize=False).classes('text-2xl text-center my-2 text-purple-800')

            ui.label("Current Image").classes('text-sm font-bold text-gray-500 mb-2')
            if self.logic.current_old_image_b64:
                ui.image(self.logic.current_old_image_b64).classes('w-full rounded mb-4')
            else:
                ui.label("No Image").classes('text-gray-400 italic text-center py-10 mb-4')

    def build_right_panel(self):
        with ui.column().classes('flex-1'):
            with ui.row().classes('w-full justify-between items-center mb-2'):
                def on_search_change(e):
                    self.logic.current_term = e.value
                    self.current_page = 1
                    self.loaded_images = []
                    self.refresh_results()

                ui.input(label="Search Query", value=self.logic.current_term) \
                    .on('keydown.enter', lambda e: on_search_change(e.sender)) \
                    .props('outlined dense').classes('w-2/3')
                
                ui.button("Skip Card", on_click=self.skip_card) \
                    .props('color=grey-5 flat icon=skip_next').classes('font-bold')

            self.results_area = ui.column().classes('w-full')
            self.refresh_results()

    def refresh_results(self, append=False):
        if not self.results_area: return
        
        if not append:
            self.loaded_images = []
            self.results_area.clear()
            
        with self.results_area:
            if not self.loaded_images and not append:
                ui.label(f"Loading from {self.current_provider.capitalize()}...").classes('animate-pulse text-blue-500')

            def fetch_and_show():
                try:
                    new_images = self.searcher.search(
                        self.current_provider, 
                        self.logic.current_term, 
                        count=self.logic.count, 
                        page=self.current_page
                    )

                    if not new_images:
                        notify(f"No more results on {self.current_provider.capitalize()}.", type='warning')
                        self.results_area.clear()
                        return

                    self.loaded_images.extend(new_images)
                    self.results_area.clear()
                    
                    with self.results_area:
                        with ui.grid(columns=3).classes('w-full gap-4'):
                            for img in self.loaded_images:
                                with ui.card().classes('cursor-pointer hover:ring-4 hover:ring-green-400 transition-all p-0') as card:
                                    ui.image(img['thumb']).classes('h-48 w-full object-cover')
                                    # Need a default arg binding for the lambda loop
                                    card.on('click', lambda _, i=img: self.select_image(i))
                        
                        ui.button("Load More Results", on_click=self.load_more_images) \
                            .classes('w-full mt-4 bg-gray-200 text-gray-800 hover:bg-gray-300')

                except ValueError as e:
                    self.results_area.clear()
                    notify(str(e), type='negative')
                    with self.results_area:
                        ui.label("⚠️ Authentication Error").classes('text-red-600 text-xl font-bold mt-4')
                        ui.label(str(e)).classes('text-red-500 text-lg')
                        ui.label("Click the Settings gear icon in the top right to update your API key.").classes('text-gray-600 mt-2')
                except Exception as e:
                    self.results_area.clear()
                    notify(f"API Error: {str(e)}", type='negative')
                    with self.results_area:
                        ui.label("⚠️ Connection Error").classes('text-orange-600 text-xl font-bold mt-4')
                        ui.label(f"Failed to fetch from {self.current_provider}: {str(e)}").classes('text-orange-500 text-lg')

            ui.timer(0.1, fetch_and_show, once=True)

def parse_arguments():
    config = ConfigManager()
    parser = argparse.ArgumentParser(description="Anki Image Fetcher GUI")
    parser.add_argument("--deck", default=None)
    # The rest are handled via config mostly now or defaults
    return parser.parse_args()

@ui.page('/')
def index_page():
    args = parse_arguments()
    config = ConfigManager()
    anki = AnkiClient()
    logic = CardManagerLogic(config, anki)
    searcher = ImageSearcher(config)
    
    missing = [k for k in ["PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "FREEPIK_API_KEY"] if not config.get(k)]
    if len(missing) == 3:
        ui.notify("Please configure API keys in Settings", type='warning', close_button=True, timeout=0)

    app_ui = AppUI(logic, searcher, args)

    with ui.column().classes('w-full max-w-6xl mx-auto p-4'):
        with ui.row().classes('w-full justify-between items-center mb-4'):
            ui.label("Anki Image Updater").classes('text-2xl font-bold')
            app_ui.status_label = ui.label("Ready to start...").classes('text-xl text-blue-600 font-semibold')
        
        app_ui.main_container = ui.column().classes('w-full min-h-[500px] border border-gray-200 rounded-lg p-4 bg-white shadow-sm')
        settings_dialog = app_ui.build_settings_dialog()

        with ui.row().classes('absolute top-4 right-4'):
             ui.button(icon='settings', on_click=settings_dialog.open).props('flat round color=grey-7')

        if args.deck:
            with app_ui.main_container:
                 ui.button("Start Processing", on_click=lambda: app_ui.load_cards()).classes('bg-green-600')
        else:
            with app_ui.main_container:
                ui.label("Select a Deck to Begin:").classes('text-lg mb-2')
                decks = anki.fetch_decks()
                if decks:
                    select = ui.select(decks, label="Deck").classes('w-1/2')
                    ui.button("Start", on_click=lambda: app_ui.start_deck_load(select.value)).classes('bg-blue-600 mt-4')
                else:
                    ui.label("Could not fetch decks. Is Anki running?").classes('text-red-500')

def start_app():
    import asyncio
    import webbrowser
    
    async def check_shutdown():
        print("🔌 Client disconnected. Waiting 4s to see if it's a refresh...", flush=True)
        await asyncio.sleep(4.0)
        count = len(client.Client.instances)
        if count == 0:
            print("❌ No clients connected. Shutting down server...", flush=True)
            app.shutdown()
        else:
            print("✅ Client reconnected (or other tabs open). Staying alive.", flush=True)
            
    app.on_disconnect(lambda: asyncio.create_task(check_shutdown()))

    def open_browser():
        webbrowser.open("http://localhost:8080/")
    
    app.on_startup(open_browser)

    print("🚀 Server starting on http://localhost:8080...", flush=True)
    ui.run(title="Anki Image Updater", reload=False, dark=False, show=False)
    print("👋 Application closed. You can close this terminal.", flush=True)
    sys.exit(0)

if __name__ in {"__main__", "__mp_main__"}:
    import multiprocessing
    multiprocessing.freeze_support() 
    start_app()