import sys
import os
import asyncio
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
        self._prefetch_task = None  # Background search pre-fetch
        self._is_navigating = False  # Guard against double-clicks during async navigation
        self._fetch_generation = 0  # Incremented on every new search; stale tasks self-discard
        
        # UI Elements
        self.status_label = None
        self.main_container = None
        self.results_area = None

    async def start_deck_load(self, deck_name):
        self.args.deck = deck_name
        await self.load_cards()

    async def load_cards(self):
        # Show loading state immediately (synchronous, before any await)
        # so the user gets instant feedback instead of a frozen UI.
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                ui.label("Scanning deck...").classes('text-blue-500 animate-pulse text-lg py-8')
        if self.status_label:
            self.status_label.set_text("Loading...")

        success, message = await self.logic.load_deck(self.args.deck)
        if not success:
            notify(message, type='warning')
            if self.main_container:
                self.main_container.clear()
                with self.main_container:
                    ui.label(f"⚠️ {message}").classes('text-orange-500 text-lg py-8')
            return
        await self.next_card()

    async def next_card(self):
        found = await self.logic.advance_to_next_valid_card()
        if not found:
            notify("All cards processed!", type='positive')
            if self.status_label: self.status_label.set_text("All Done!")
            if self.main_container: self.main_container.clear()
            return
            
        # Reset pagination/images for new card
        self.current_page = 1
        self.loaded_images = []
        
        # Kick off the API search immediately in the background before building UI.
        # By the time the UI finishes painting, results are often already here.
        # Snapshot params NOW so the task uses the right term even if state changes.
        self._fetch_generation += 1
        gen = self._fetch_generation
        provider = self.current_provider
        term = self.logic.current_term
        page = self.current_page
        self._prefetch_task = asyncio.create_task(self._do_search(provider, term, page))
        self._prefetch_generation = gen  # So fetch_and_show knows which gen this task belongs to
        
        self.refresh_ui_content()

    async def _do_search(self, provider, term, page):
        """Runs a search with explicit snapshot params — never reads from self mid-flight."""
        return await self.searcher.search(
            provider,
            term,
            count=self.logic.count,
            page=page
        )

    def set_provider(self, provider):
        self.current_provider = provider
        self.current_page = 1
        self.loaded_images = []
        # Cancel the in-flight prefetch (not just null it) so it doesn't waste bandwidth
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()
        self._prefetch_task = None
        self.refresh_ui_content()

    def load_more_images(self):
        self.current_page += 1
        self.refresh_results(append=True)

    async def select_image(self, img_data):
        """
        Immediately advances to the next card, and fires off the Anki update
        as a background task so the user doesn't have to wait.
        """
        if self._is_navigating:
            return  # Ignore clicks while a previous selection is still processing
        self._is_navigating = True

        from nicegui import context as ng_context
        # Capture context NOW, before we lose it in the background task
        current_client = ng_context.client
        
        # Snapshot the current card state BEFORE advancing to the next card.
        # The background task runs later, by which point self.logic.current_note
        # has already moved on — this prevents updating the wrong card.
        snapshot_note = self.logic.current_note
        snapshot_term = self.logic.current_term

        # Immediately clear the results grid so stale image cards
        # can't receive further clicks while next_card() is awaiting Anki.
        if self.results_area:
            self.results_area.clear()
            with self.results_area:
                ui.label(f"Saving '{snapshot_term}'...").classes('text-blue-500 animate-pulse py-4')

        async def _background_update():
            with current_client:  # Restore NiceGUI slot context for UI calls
                try:
                    updated_term = await self.logic.apply_image_to_card(
                        img_data,
                        note=snapshot_note,
                        term=snapshot_term,
                    )
                    logger.info(f"Background update complete for '{updated_term}'")
                    notify(f"✅ Saved '{updated_term}'", type='positive')
                except ActionError as e:
                    notify(str(e), type='negative')
                    logger.error(f"Background update failed: {e}")
                except Exception as e:
                    logger.exception("Unexpected error in background image update")
                    notify(f"Error saving image: {e}", type='negative')

        # Fire off the background Anki update — user won't wait for this
        asyncio.create_task(_background_update())
        # Immediately advance to the next card in context
        try:
            await self.next_card()
        finally:
            self._is_navigating = False

    async def skip_card(self):
        if self._is_navigating:
            return
        self._is_navigating = True
        try:
            term = await self.logic.skip_card()
            if term:
                notify(f"Skipped '{term}'", type='warning')
            await self.next_card()
        finally:
            self._is_navigating = False

    def build_settings_dialog(self):
        cfg = self.logic.config
        with ui.dialog() as settings_dialog, ui.card().classes('w-full max-w-lg'):
            ui.label('Settings').classes('text-xl font-bold mb-2')
            with ui.column().classes('w-full gap-2'):

                ui.label("API Keys").classes('text-sm font-bold text-gray-600 mt-2')
                ui.input("Pexels API Key",      value=cfg.get("PEXELS_API_KEY"),    on_change=lambda e: cfg_vals.__setitem__('pexels',    e.value)).props('type=password outlined dense').classes('w-full')
                ui.input("Unsplash Access Key", value=cfg.get("UNSPLASH_ACCESS_KEY"), on_change=lambda e: cfg_vals.__setitem__('unsplash', e.value)).props('type=password outlined dense').classes('w-full')
                ui.input("Freepik API Key",     value=cfg.get("FREEPIK_API_KEY"),   on_change=lambda e: cfg_vals.__setitem__('freepik',   e.value)).props('type=password outlined dense').classes('w-full')

                with ui.expansion("Advanced", icon="tune").classes('w-full mt-2 border rounded'):
                    with ui.column().classes('w-full gap-2 p-2'):
                        ui.label("Anki Field Names").classes('text-sm font-bold text-gray-600 mt-1')
                        ui.input("Search Term Field",  value=cfg.get("DEFAULT_FIELD_SEARCH"), on_change=lambda e: cfg_vals.__setitem__('field_search',  e.value)).props('dense outlined').classes('w-full')
                        ui.input("Image Field",        value=cfg.get("DEFAULT_FIELD_IMAGE"),  on_change=lambda e: cfg_vals.__setitem__('field_image',   e.value)).props('dense outlined').classes('w-full')
                        ui.input("Image Source Field", value=cfg.get("DEFAULT_FIELD_SOURCE"), on_change=lambda e: cfg_vals.__setitem__('field_source',  e.value)).props('dense outlined').classes('w-full')

                        ui.label("Behaviour").classes('text-sm font-bold text-gray-600 mt-3')
                        ui.input("Images per Term", value=str(cfg.get("DEFAULT_IMAGES_PER_TERM", 6)), on_change=lambda e: cfg_vals.__setitem__('images_per_term', e.value)).props('dense outlined type=number').classes('w-full')
                        ui.input("Tag Added on Save", value=cfg.get("DEFAULT_TAG"), on_change=lambda e: cfg_vals.__setitem__('tag', e.value)).props('dense outlined').classes('w-full')

                        ui.label(f"Config file: {cfg.config_path}").classes('text-xs text-gray-400 mt-2')

                with ui.row().classes('w-full justify-end mt-4'):
                    # Use a mutable dict so lambdas capture current input values at save time
                    cfg_vals = {
                        'pexels':         cfg.get("PEXELS_API_KEY"),
                        'unsplash':       cfg.get("UNSPLASH_ACCESS_KEY"),
                        'freepik':        cfg.get("FREEPIK_API_KEY"),
                        'field_search':   cfg.get("DEFAULT_FIELD_SEARCH"),
                        'field_image':    cfg.get("DEFAULT_FIELD_IMAGE"),
                        'field_source':   cfg.get("DEFAULT_FIELD_SOURCE"),
                        'images_per_term': str(cfg.get("DEFAULT_IMAGES_PER_TERM", 6)),
                        'tag':            cfg.get("DEFAULT_TAG"),
                    }

                    def save_settings():
                        cfg.set("PEXELS_API_KEY",        cfg_vals['pexels'].strip())
                        cfg.set("UNSPLASH_ACCESS_KEY",   cfg_vals['unsplash'].strip())
                        cfg.set("FREEPIK_API_KEY",       cfg_vals['freepik'].strip())
                        cfg.set("DEFAULT_FIELD_SEARCH",  cfg_vals['field_search'].strip())
                        cfg.set("DEFAULT_FIELD_IMAGE",   cfg_vals['field_image'].strip())
                        cfg.set("DEFAULT_FIELD_SOURCE",  cfg_vals['field_source'].strip())
                        cfg.set("DEFAULT_TAG",           cfg_vals['tag'].strip())
                        try:
                            cfg.set("DEFAULT_IMAGES_PER_TERM", int(cfg_vals['images_per_term']))
                        except ValueError:
                            pass
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
            render_provider_btn('wikimedia')

    def build_left_panel(self):
        with ui.card().classes('w-1/4 min-w-[200px] p-2 bg-gray-50'):
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
        
        # Snapshot all the params that define this particular search.
        # Increment generation so any currently-running fetch_and_show knows it's stale.
        if not append:
            self.loaded_images = []
            self.results_area.clear()
            self._fetch_generation += 1

        my_generation = self._fetch_generation
        provider = self.current_provider
        term = self.logic.current_term
        page = self.current_page
            
        # Capture NiceGUI slot context NOW (synchronously) before create_task loses it.
        # The same pattern used in select_image — must be done while we're in a request handler.
        from nicegui import context as ng_context
        current_client = ng_context.client

        with self.results_area:
            if not self.loaded_images and not append:
                ui.label(f"Loading from {provider.capitalize()}...").classes('animate-pulse text-blue-500')

            async def fetch_and_show():
                with current_client:  # Restore slot context so notify() and ui.* work
                    try:
                        # Use the pre-fetched task if it belongs to this same generation
                        if self._prefetch_task and not append and getattr(self, '_prefetch_generation', -1) == my_generation:
                            task = self._prefetch_task
                            self._prefetch_task = None
                            new_images = await task
                        else:
                            new_images = await self._do_search(provider, term, page)

                        # Stale check: discard if a newer search started while we were awaiting
                        if self._fetch_generation != my_generation:
                            logger.debug(f"Discarding stale search (gen {my_generation})")
                            return

                        if not new_images:
                            self.results_area.clear()
                            with self.results_area:
                                ui.label("🔍 No results found").classes('text-gray-500 text-xl font-bold mt-4')
                                ui.label(f"Try a different search term or switch provider.").classes('text-gray-400 mt-1')
                            return

                        self.loaded_images.extend(new_images)
                        self.results_area.clear()
                        
                        with self.results_area:
                            with ui.grid(columns=3).classes('w-full gap-4'):
                                for img in self.loaded_images:
                                    with ui.card().classes('cursor-pointer hover:ring-4 hover:ring-green-400 p-0') as card:
                                        ui.image(img['thumb']).classes('h-48 w-full object-cover')
                                        card.on('click', lambda _, i=img: self.select_image(i))
                            
                            ui.button("Load More Results", on_click=self.load_more_images) \
                                .classes('w-full mt-4 bg-gray-200 text-gray-800 hover:bg-gray-300')

                    except asyncio.CancelledError:
                        pass  # Prefetch was cancelled (e.g. provider switched) — silently stop
                    except ValueError as e:
                        if self._fetch_generation != my_generation: return
                        self.results_area.clear()
                        notify(str(e), type='negative')
                        with self.results_area:
                            ui.label("⚠️ Authentication Error").classes('text-red-600 text-xl font-bold mt-4')
                            ui.label(str(e)).classes('text-red-500 text-lg')
                            ui.label("Click the Settings gear icon in the top right to update your API key.").classes('text-gray-600 mt-2')
                    except Exception as e:
                        if self._fetch_generation != my_generation: return
                        self.results_area.clear()
                        notify(f"API Error: {str(e)}", type='negative')
                        with self.results_area:
                            ui.label("⚠️ Connection Error").classes('text-orange-600 text-xl font-bold mt-4')
                            ui.label(f"Failed to fetch from {provider}: {str(e)}").classes('text-orange-500 text-lg')

            asyncio.create_task(fetch_and_show())


def parse_arguments():
    config = ConfigManager()
    parser = argparse.ArgumentParser(description="Anki Image Fetcher GUI")
    parser.add_argument("--deck", default=None)
    return parser.parse_args()

@ui.page('/')
async def index_page():
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
                decks = await anki.fetch_decks()
                if decks:
                    select = ui.select(decks, label="Deck").classes('w-1/2')
                    # Pass the coroutine directly — NiceGUI awaits it with correct context
                    ui.button("Start", on_click=lambda: app_ui.start_deck_load(select.value)).classes('bg-blue-600 mt-4')
                else:
                    ui.label("Could not fetch decks. Is Anki running?").classes('text-red-500')

def start_app():
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
        import webbrowser
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