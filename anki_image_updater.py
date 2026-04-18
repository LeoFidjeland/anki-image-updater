import sys
import os
import re
import html
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from platformdirs import user_log_dir

from nicegui import ui, app, client

from config_manager import APP_NAME, AUTHOR, ConfigManager
from anki_client import AnkiClient, AnkiConnectError
from search_providers import ImageSearcher
from core import CardManagerLogic, ActionError
from utils import strip_html_to_plain

# Log to user_log_dir so double-clicked binaries don't try to write to cwd
# (which may be /, C:\Windows\System32, or otherwise non-writable).
_log_dir = Path(user_log_dir(APP_NAME, AUTHOR))
_log_dir.mkdir(parents=True, exist_ok=True)
LOG_FILE = _log_dir / "anki_image_updater.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


class _SuppressAnkiConnectHttpInfo(logging.Filter):
    """Drop httpx/httpcore INFO spam for successful AnkiConnect (localhost:8765) calls."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True
        msg = record.getMessage()
        if "8765" not in msg:
            return True
        if "localhost" in msg or "127.0.0.1" in msg:
            return False
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_SuppressAnkiConnectHttpInfo())

logger = logging.getLogger(__name__)

def notify(msg, type='info'):
    ui.notify(msg, type=type, position='bottom-left')

class AppUI:
    # `gap-4` in Tailwind ≈ 1rem (16px). Normalized by a reference column width so it
    # adds to the same scale as th/tw height ratios when balancing columns.
    _GAP_PX = 16
    _REFERENCE_COLUMN_WIDTH_PX = 400

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
        self._result_columns = None  # list of 3 vertical stacks (kept when appending pages)
        self._load_more_btn = None
        self._load_more_in_progress = False
        self._session_skipped = 0
        self._session_replaced = 0

        # UI Elements
        self.status_label_idle = None
        self.status_stats_row = None
        self.status_remaining = None
        self.status_skipped = None
        self.status_replaced = None
        self.provider_slot = None
        self.search_bar_slot = None
        self.main_container = None
        self.results_area = None

    async def start_deck_load(self, deck_name):
        self.args.deck = deck_name
        await self.load_cards()

    async def load_cards(self):
        self.searcher.clear_search_cache()
        # Show loading state immediately (synchronous, before any await)
        # so the user gets instant feedback instead of a frozen UI.
        if self.provider_slot:
            self.provider_slot.clear()
        if self.search_bar_slot:
            self.search_bar_slot.clear()
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                ui.label("Scanning deck...").classes('text-blue-500 animate-pulse text-lg py-8')
        if self.status_label_idle:
            self.status_label_idle.set_text("Loading...")
            self.status_label_idle.visible = True
        if self.status_stats_row:
            self.status_stats_row.visible = False

        success, message = await self.logic.load_deck(self.args.deck)
        if not success:
            notify(message, type='warning')
            if self.search_bar_slot:
                self.search_bar_slot.clear()
            if self.main_container:
                self.main_container.clear()
                with self.main_container:
                    ui.label(f"⚠️ {message}").classes('text-orange-500 text-lg py-8')
            self._set_status_idle()
            if self.status_label_idle:
                self.status_label_idle.set_text("Ready to start...")
            return
        self._session_skipped = 0
        self._session_replaced = 0
        await self.next_card()

    async def next_card(self):
        found = await self.logic.advance_to_next_valid_card()
        if not found:
            notify("All cards processed!", type='positive')
            self._set_status_done()
            if self.provider_slot:
                self.provider_slot.clear()
            if self.search_bar_slot:
                self.search_bar_slot.clear()
            if self.main_container:
                self.main_container.clear()
            return

        self.searcher.clear_search_cache()
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
        self._fetch_generation += 1
        self._refresh_provider_ui()

    def _refresh_provider_ui(self):
        """Provider buttons + search results only; keep card info column (left) to avoid flicker."""
        self._update_status_bar()
        if self.provider_slot:
            self.provider_slot.clear()
            with self.provider_slot:
                self.build_provider_toggles()
        if self.results_area:
            self.refresh_results(append=False)

    def load_more_images(self):
        if self._load_more_in_progress:
            return
        self.current_page += 1
        self.refresh_results(append=True)

    @staticmethod
    def _normalized_height_ratio(img):
        """
        Predicted stacked height at a fixed column width (proportional to th/tw).
        Matches the UI fallback when dimensions are missing (aspect 4:3 → h/w = 3/4).
        """
        tw, th = img.get('thumb_width'), img.get('thumb_height')
        if tw and th and tw > 0 and th > 0:
            return th / tw
        return 3.0 / 4.0

    @classmethod
    def _gap_height_ratio(cls):
        """Vertical gap between stacked cards (gap-4), as height / reference column width."""
        return cls._GAP_PX / cls._REFERENCE_COLUMN_WIDTH_PX

    @staticmethod
    def _balanced_column_indices(images):
        """
        Greedy shortest-column: each image goes to the column with smallest predicted height.
        Height sums image th/tw ratios plus one gap between each pair of stacked items.
        """
        heights = [0.0, 0.0, 0.0]
        counts = [0, 0, 0]
        gap = AppUI._gap_height_ratio()
        columns = []
        for img in images:
            r = AppUI._normalized_height_ratio(img)
            c = min(range(3), key=lambda i: heights[i])
            if counts[c] > 0:
                heights[c] += gap
            heights[c] += r
            counts[c] += 1
            columns.append(c)
        return columns

    def _render_image_card(self, img):
        """One clickable thumbnail card; must be used inside one of the three column stacks."""
        with ui.card().classes(
            'w-full max-w-full min-w-0 cursor-pointer '
            'hover:ring-4 hover:ring-green-400 p-0 overflow-hidden rounded'
        ) as card:
            tw, th = img.get('thumb_width'), img.get('thumb_height')
            with ui.element('div').classes('w-full relative bg-gray-100') as slot:
                if tw and th:
                    slot.style(f'aspect-ratio: {tw} / {th}')
                else:
                    slot.classes('aspect-[4/3]')
                ui.image(img['thumb']).classes(
                    'absolute inset-0 w-full h-full object-contain'
                ).props('loading=lazy no-transition')
            card.on('click', lambda _, i=img: self.select_image(i))

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
        raw_card = (
            (snapshot_note or {})
            .get('fields', {})
            .get(self.logic.field_term, {})
            .get('value', '')
        )
        snapshot_card_term = raw_card.split('<')[0].strip() or snapshot_term

        # Immediately clear the results grid so stale image cards
        # can't receive further clicks while next_card() is awaiting Anki.
        if self.results_area:
            self.results_area.clear()
            with self.results_area:
                ui.label(f"Saving '{snapshot_card_term}'...").classes(
                    'text-blue-500 animate-pulse py-4'
                )

        async def _background_update():
            with current_client:  # Restore NiceGUI slot context for UI calls
                try:
                    updated_term = await self.logic.apply_image_to_card(
                        img_data,
                        note=snapshot_note,
                        term=snapshot_term,
                    )
                    logger.info("Update succeeded for '%s'", updated_term)
                    self._session_replaced += 1
                    self._update_status_bar()
                    notify(f"✅ Saved '{updated_term}'", type='positive')
                except ActionError as e:
                    notify(str(e), type='negative')
                    logger.error("Update failed: %s", e)
                except AnkiConnectError as e:
                    logger.error("Update failed (Anki): %s", e)
                    notify(f"Could not save to Anki: {e}", type='negative')
                except Exception as e:
                    logger.exception("Unexpected error in image update")
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
            try:
                term = await self.logic.skip_card()
            except AnkiConnectError as e:
                logger.error("Skip card failed (Anki): %s", e)
                notify(f"Could not tag skipped card in Anki: {e}", type='negative')
                return
            if term:
                self._session_skipped += 1
                notify(f"Skipped '{term}'", type='warning')
            await self.next_card()
        finally:
            self._is_navigating = False

    async def ok_card(self):
        if self._is_navigating:
            return
        self._is_navigating = True
        try:
            try:
                term = await self.logic.ok_card()
            except AnkiConnectError as e:
                logger.error("OK card failed (Anki): %s", e)
                notify(f"Could not tag card in Anki: {e}", type='negative')
                return
            if term:
                self._session_replaced += 1
                notify(f"Marked OK: '{term}'", type='positive')
            await self.next_card()
        finally:
            self._is_navigating = False

    async def unset_image(self):
        if self._is_navigating:
            return
        self._is_navigating = True
        try:
            try:
                term = await self.logic.unset_image()
            except ActionError as e:
                notify(str(e), type='negative')
                return
            except AnkiConnectError as e:
                logger.error("Unset image failed (Anki): %s", e)
                notify(f"Could not update card in Anki: {e}", type='negative')
                return
            if term:
                self._session_replaced += 1
                notify(f"Unset image for '{term}'", type='positive')
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
                ui.input("Pixabay API Key",     value=cfg.get("PIXABAY_API_KEY"),   on_change=lambda e: cfg_vals.__setitem__('pixabay',   e.value)).props('type=password outlined dense').classes('w-full')

                with ui.expansion("Advanced", icon="tune").classes('w-full mt-2 border rounded'):
                    with ui.column().classes('w-full gap-2 p-2'):
                        ui.label("Anki Field Names").classes('text-sm font-bold text-gray-600 mt-1')
                        ui.input("Search Term Field",  value=cfg.get("DEFAULT_FIELD_SEARCH"), on_change=lambda e: cfg_vals.__setitem__('field_search',  e.value)).props('dense outlined').classes('w-full')
                        ui.input("Image Field",        value=cfg.get("DEFAULT_FIELD_IMAGE"),  on_change=lambda e: cfg_vals.__setitem__('field_image',   e.value)).props('dense outlined').classes('w-full')
                        ui.input("Image Source Field", value=cfg.get("DEFAULT_FIELD_SOURCE"), on_change=lambda e: cfg_vals.__setitem__('field_source',  e.value)).props('dense outlined').classes('w-full')

                        ui.label("Behaviour").classes('text-sm font-bold text-gray-600 mt-3')
                        ui.input("Images per Term", value=str(cfg.get("DEFAULT_IMAGES_PER_TERM")), on_change=lambda e: cfg_vals.__setitem__('images_per_term', e.value)).props('dense outlined type=number').classes('w-full')
                        ui.input("Tag Added on Save", value=cfg.get("DEFAULT_TAG"), on_change=lambda e: cfg_vals.__setitem__('tag', e.value)).props('dense outlined').classes('w-full')

                        ui.label(f"Config file: {cfg.config_path}").classes('text-xs text-gray-400 mt-2')

                with ui.row().classes('w-full justify-end mt-4'):
                    # Use a mutable dict so lambdas capture current input values at save time
                    cfg_vals = {
                        'pexels':         cfg.get("PEXELS_API_KEY"),
                        'unsplash':       cfg.get("UNSPLASH_ACCESS_KEY"),
                        'freepik':        cfg.get("FREEPIK_API_KEY"),
                        'pixabay':        cfg.get("PIXABAY_API_KEY"),
                        'field_search':   cfg.get("DEFAULT_FIELD_SEARCH"),
                        'field_image':    cfg.get("DEFAULT_FIELD_IMAGE"),
                        'field_source':   cfg.get("DEFAULT_FIELD_SOURCE"),
                        'images_per_term': str(cfg.get("DEFAULT_IMAGES_PER_TERM")),
                        'tag':            cfg.get("DEFAULT_TAG"),
                    }

                    def save_settings():
                        cfg.set("PEXELS_API_KEY",        cfg_vals['pexels'].strip())
                        cfg.set("UNSPLASH_ACCESS_KEY",   cfg_vals['unsplash'].strip())
                        cfg.set("FREEPIK_API_KEY",       cfg_vals['freepik'].strip())
                        cfg.set("PIXABAY_API_KEY",       cfg_vals['pixabay'].strip())
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

    def _set_status_idle(self):
        if self.status_label_idle:
            self.status_label_idle.visible = True
        if self.status_stats_row:
            self.status_stats_row.visible = False

    def _set_status_processing(self, remaining, skipped, replaced):
        if self.status_label_idle:
            self.status_label_idle.visible = False
        if self.status_stats_row:
            self.status_stats_row.visible = True
        if self.status_remaining:
            self.status_remaining.set_text(f"{remaining} Remaining")
        if self.status_skipped:
            self.status_skipped.set_text(f"{skipped} Skipped")
        if self.status_replaced:
            self.status_replaced.set_text(f"{replaced} Replaced")

    def _set_status_done(self):
        if self.status_label_idle:
            self.status_label_idle.visible = False
        if self.status_stats_row:
            self.status_stats_row.visible = True
        if self.status_remaining:
            self.status_remaining.set_text("0 Remaining")
        if self.status_skipped:
            self.status_skipped.set_text(f"{self._session_skipped} Skipped")
        if self.status_replaced:
            self.status_replaced.set_text(f"{self._session_replaced} Replaced")

    def _update_status_bar(self):
        if not self.status_remaining:
            return
        if not self.logic.valid_notes:
            self._set_status_idle()
            return
        remaining = self.logic.get_remaining_count()
        self._set_status_processing(
            remaining, self._session_skipped, self._session_replaced
        )

    @staticmethod
    def _strip_html_to_plain(html: str) -> str:
        return strip_html_to_plain(html)

    @staticmethod
    def _is_valid_http_url(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return False
        p = urlparse(s)
        return p.scheme in ("http", "https") and bool(p.netloc)

    @classmethod
    def _http_url_from_source_field(cls, raw: str) -> Optional[str]:
        """If the field is a bare http(s) URL or a single anchor with http(s) href, return URL."""
        s = (raw or "").strip()
        if not s:
            return None
        if cls._is_valid_http_url(s):
            return s
        m = re.search(r'href\s*=\s*"([^"]+)"', s, re.I)
        if not m:
            m = re.search(r"href\s*=\s*'([^']+)'", s, re.I)
        if m and cls._is_valid_http_url(m.group(1)):
            return m.group(1).strip()
        return None

    def refresh_ui_content(self):
        """Full main-area rebuild (new card): search bar, left panel, and results grid."""
        self._update_status_bar()

        if self.provider_slot:
            self.provider_slot.clear()
            with self.provider_slot:
                self.build_provider_toggles()
        if self.search_bar_slot:
            self.search_bar_slot.clear()
            with self.search_bar_slot:
                self.build_search_bar()
        if self.main_container:
            self.main_container.clear()
            with self.main_container:
                # Full width: 4 equal columns — info | image | image | image
                with ui.element('div').classes(
                    'grid grid-cols-1 lg:grid-cols-4 gap-4 lg:gap-6 w-full items-start'
                ):
                    with ui.column().classes('min-w-0'):
                        self.build_left_panel()
                    with ui.column().classes('lg:col-span-3 min-w-0'):
                        self.build_results_panel()

    def build_provider_toggles(self):
        def render_provider_btn(provider_name):
            is_active = self.current_provider == provider_name
            btn_props = 'color=blue-6 text-color=white unelevated' if is_active else 'color=white text-color=grey-9 outline'
            ui.button(provider_name.capitalize(), on_click=lambda p=provider_name: self.set_provider(p)) \
                .props(btn_props).classes('px-3 sm:px-4 font-bold text-sm')

        render_provider_btn('pexels')
        render_provider_btn('unsplash')
        render_provider_btn('freepik')
        render_provider_btn('pixabay')
        render_provider_btn('wikimedia')

    def _left_panel_heading(self, title: str):
        ui.label(title).classes(
            'text-xs font-semibold uppercase tracking-wide text-slate-500 mb-1'
        )

    def _left_panel_large_html(self, raw: str):
        ui.html(raw, sanitize=False).classes(
            'text-2xl sm:text-3xl leading-snug text-black font-medium break-words text-left w-full'
        )

    def _left_panel_large_plain(self, text: str):
        ui.label(text).classes(
            'text-xl sm:text-2xl leading-snug text-slate-900 font-medium break-words'
        )

    def _left_panel_body(self, raw: str):
        plain = self._strip_html_to_plain(raw)
        if not plain:
            return
        ui.label(plain).classes(
            'text-sm text-slate-700 leading-relaxed break-words whitespace-pre-wrap'
        )

    def build_search_bar(self):
        """
        Unset (left), search (center), OK + Skip (right) on wide screens; stacked on narrow.
        """

        def on_search_change(e):
            self.logic.current_term = e.value
            self.current_page = 1
            self.loaded_images = []
            if self._prefetch_task and not self._prefetch_task.done():
                self._prefetch_task.cancel()
            self._prefetch_task = None
            self._fetch_generation += 1
            self.refresh_results()

        with ui.element('div').classes(
            'w-full flex flex-col sm:flex-row sm:items-center gap-y-2 sm:gap-y-0 '
            'gap-x-3 mb-1 sm:mb-1.5'
        ):
            with ui.element('div').classes(
                'w-full sm:flex-1 min-w-0 flex justify-start items-center'
            ):
                ui.button("Unset image", on_click=self.unset_image) \
                    .props('color=grey-5 flat icon=broken_image').classes('font-bold shrink-0')
            with ui.element('div').classes(
                'w-full sm:w-auto sm:flex-none sm:min-w-0 flex justify-center'
            ):
                ui.input(label="Search Query", value=self.logic.current_term) \
                    .on('keydown.enter', lambda e: on_search_change(e.sender)) \
                    .props('outlined dense').classes(
                        'w-full min-w-0 max-w-xl sm:w-96 md:max-w-2xl'
                    )
            with ui.element('div').classes(
                'w-full sm:flex-1 min-w-0 flex justify-end items-center gap-2'
            ):
                with ui.row().classes('gap-2 items-center shrink-0'):
                    ui.button("OK", on_click=self.ok_card) \
                        .props('color=grey-5 flat icon=check_box').classes('font-bold shrink-0')
                    ui.button("Skip Card", on_click=self.skip_card) \
                        .props('color=grey-5 flat icon=skip_next').classes('font-bold shrink-0')

    def build_left_panel(self):
        with ui.card().classes(
            'w-full min-w-0 p-4 bg-slate-50 border border-slate-200/90 rounded-xl shadow-sm'
        ):
            with ui.column().classes('w-full gap-4'):
                note = self.logic.current_note
                if not note:
                    ui.label("No card loaded.").classes('text-slate-400 text-sm')
                    return

                fields = note['fields']

                # Tibetan
                tibetan_val = fields.get('Tibetan', {}).get('value', '').strip()
                if tibetan_val:
                    self._left_panel_heading('Tibetan')
                    self._left_panel_large_html(tibetan_val)

                # English (configured search term field, e.g. English)
                term = self.logic.current_term
                if term:
                    self._left_panel_heading(self.logic.field_term)
                    self._left_panel_large_plain(term)

                ui.separator().classes('opacity-60')

                # Current image
                self._left_panel_heading('Image')
                if self.logic.current_old_image_b64:
                    src = html.escape(
                        self.logic.current_old_image_b64, quote=True
                    )
                    with ui.element("div").classes(
                        "w-full rounded-lg border border-slate-200 shadow-md "
                        "overflow-hidden bg-white"
                    ):
                        ui.html(
                            f'<img src="{src}" class="w-full h-auto max-w-full block '
                            f'object-contain" alt="" />',
                            sanitize=False,
                        )
                else:
                    ui.label("No image yet").classes(
                        'text-slate-400 italic text-sm py-6 text-center border border-dashed '
                        'border-slate-200 rounded-lg w-full'
                    )

                source_raw = fields.get(self.logic.field_source, {}).get('value', '')
                if source_raw.strip():
                    ui.separator().classes('opacity-60')
                    self._left_panel_heading(self.logic.field_source)
                    link_url = self._http_url_from_source_field(source_raw)
                    if link_url:
                        link_label = self._strip_html_to_plain(source_raw) or link_url
                        ui.link(link_label, link_url, new_tab=True).classes(
                            'text-sm text-blue-700 hover:underline break-all'
                        )
                    else:
                        safe = html.escape(source_raw)
                        ui.html(
                            f'<div class="whitespace-pre-wrap break-words text-sm text-slate-700 '
                            f'font-mono bg-slate-100/90 p-2 rounded-lg border border-slate-200/90">'
                            f'{safe}</div>',
                            sanitize=False,
                        )

                for label, key in (
                    ('Notes', 'Notes'),
                    ('Acceptions', 'Acceptions'),
                    ('Syllables', 'Syllables'),
                    ('Example Sentence Tibetan', 'Example Sentence Tibetan'),
                    ('Example Sentence English', 'Example Sentence English'),
                ):
                    raw = fields.get(key, {}).get('value', '').strip()
                    if not raw:
                        continue
                    ui.separator().classes('opacity-60')
                    self._left_panel_heading(label)
                    self._left_panel_body(raw)

    def build_results_panel(self):
        """Right side of the 4-column layout: 3 equal image columns + load more."""
        self.results_area = ui.column().classes('w-full')
        self.refresh_results()

    def refresh_results(self, append=False):
        if not self.results_area: return
        
        # Snapshot all the params that define this particular search.
        # Generation is bumped by next_card, set_provider, or search field edit — not here —
        # so prefetch and fetch_and_show share the same generation (single API call).
        if not append:
            self.loaded_images = []
            self.results_area.clear()
            self._result_columns = None
            self._load_more_btn = None

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
                    if append:
                        self._load_more_in_progress = True
                        if self._load_more_btn:
                            self._load_more_btn.disable()
                    try:
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
                                if append:
                                    self.current_page -= 1
                                    notify("No more results for this search.", type='info')
                                    return
                                self.results_area.clear()
                                with self.results_area:
                                    ui.label("🔍 No results found").classes('text-gray-500 text-xl font-bold mt-4')
                                    ui.label(f"Try a different search term or switch provider.").classes('text-gray-400 mt-1')
                                return

                            self.loaded_images.extend(new_images)

                            if append and self._result_columns is not None:
                                # Recompute full assignment so it matches a fresh build; only render new indices.
                                cols_ix = self._balanced_column_indices(self.loaded_images)
                                start = len(self.loaded_images) - len(new_images)
                                for i in range(start, len(self.loaded_images)):
                                    with self._result_columns[cols_ix[i]]:
                                        self._render_image_card(self.loaded_images[i])
                            else:
                                self.results_area.clear()
                                self._result_columns = None
                                with self.results_area:
                                    # Three equal-width stacks (1/3 of the 3-column span = 1/4 page each).
                                    cols_ix = self._balanced_column_indices(self.loaded_images)
                                    with ui.element('div').classes(
                                        'grid grid-cols-1 sm:grid-cols-3 gap-4 w-full items-start'
                                    ):
                                        self._result_columns = []
                                        for _ in range(3):
                                            with ui.column().classes('min-w-0 gap-4') as c:
                                                self._result_columns.append(c)
                                        for img, c in zip(self.loaded_images, cols_ix):
                                            with self._result_columns[c]:
                                                self._render_image_card(img)
                                    self._load_more_btn = ui.button(
                                        "Load More Results",
                                        on_click=self.load_more_images,
                                    ).classes(
                                        'w-full mt-4 bg-gray-200 text-gray-800 hover:bg-gray-300'
                                    )

                        except asyncio.CancelledError:
                            pass  # Prefetch was cancelled (e.g. provider switched) — silently stop
                        except ValueError as e:
                            if self._fetch_generation != my_generation:
                                return
                            if append:
                                self.current_page -= 1
                            notify(str(e), type='negative')
                            if not append:
                                self.results_area.clear()
                                with self.results_area:
                                    ui.label("⚠️ Authentication Error").classes('text-red-600 text-xl font-bold mt-4')
                                    ui.label(str(e)).classes('text-red-500 text-lg')
                                    ui.label("Click the Settings gear icon in the top right to update your API key.").classes('text-gray-600 mt-2')
                        except Exception as e:
                            if self._fetch_generation != my_generation:
                                return
                            if append:
                                self.current_page -= 1
                            notify(f"API Error: {str(e)}", type='negative')
                            if not append:
                                self.results_area.clear()
                                with self.results_area:
                                    ui.label("⚠️ Connection Error").classes('text-orange-600 text-xl font-bold mt-4')
                                    ui.label(f"Failed to fetch from {provider}: {str(e)}").classes('text-orange-500 text-lg')
                    finally:
                        if append:
                            self._load_more_in_progress = False
                            if self._load_more_btn:
                                self._load_more_btn.enable()

            asyncio.create_task(fetch_and_show())


def parse_arguments():
    config = ConfigManager()
    parser = argparse.ArgumentParser(description="Anki Image Fetcher GUI")
    parser.add_argument("--deck", default=None)
    return parser.parse_args()

@ui.page('/')
async def index_page():
    # QImg defaults to a fade transition; disable for instant paint (see Quasar QImg).
    ui.add_css(
        '.q-img .q-img__image { transition: none !important; }\n'
        '.q-img .q-img__content { transition: none !important; }'
    )

    args = parse_arguments()
    config = ConfigManager()
    anki = AnkiClient()
    logic = CardManagerLogic(config, anki)
    searcher = ImageSearcher(config)
    
    missing = [k for k in ["PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "FREEPIK_API_KEY"] if not config.get(k)]
    if len(missing) == 3:
        ui.notify("Please configure API keys in Settings", type='warning', close_button=True, timeout=0)

    app_ui = AppUI(logic, searcher, args)

    with ui.column().classes('w-full max-w-[100vw] box-border px-4 sm:px-6 lg:px-8 py-2 sm:py-3'):
        # Row 1: title (left) | providers (center) | stats (right)
        # Use flex + flex-1 thirds (no arbitrary grid-* — NiceGUI’s Tailwind may omit them).
        with ui.element('div').classes(
            'w-full flex flex-col sm:flex-row sm:items-center gap-y-2 sm:gap-y-0 '
            'gap-x-2 sm:gap-x-4 mb-1.5 sm:mb-2'
        ):
            with ui.element('div').classes(
                'w-full sm:flex-1 sm:min-w-0 flex justify-start items-center'
            ):
                ui.label("Anki Image Updater").classes(
                    'text-xl sm:text-2xl font-bold text-slate-800 shrink-0 min-w-0'
                )
            with ui.element('div').classes(
                'w-full sm:flex-1 sm:min-w-0 flex justify-center items-center'
            ):
                app_ui.provider_slot = ui.row().classes(
                    'w-full min-w-0 flex flex-row flex-wrap sm:flex-nowrap '
                    'items-center justify-center gap-1.5 sm:gap-2'
                )
            with ui.element('div').classes(
                'w-full sm:flex-1 sm:min-w-0 flex justify-end items-center gap-2'
            ):
                app_ui.status_label_idle = ui.label("Ready to start...").classes(
                    'text-sm sm:text-base text-slate-500 font-medium text-right'
                )
                with ui.row().classes(
                    'items-center gap-1.5 sm:gap-2 flex-wrap justify-end'
                ) as stats_row:
                    app_ui.status_stats_row = stats_row
                    app_ui.status_stats_row.visible = False
                    app_ui.status_remaining = ui.label("").classes(
                        'text-sm sm:text-base font-semibold tabular-nums '
                        'text-[#4f8fd4]'
                    )
                    ui.label("·").classes('text-slate-300 select-none')
                    app_ui.status_skipped = ui.label("").classes(
                        'text-sm sm:text-base font-semibold tabular-nums '
                        'text-[#d4a84b]'
                    )
                    ui.label("·").classes('text-slate-300 select-none')
                    app_ui.status_replaced = ui.label("").classes(
                        'text-sm sm:text-base font-semibold tabular-nums '
                        'text-[#4faa8a]'
                    )

        app_ui.search_bar_slot = ui.column().classes('w-full')
        app_ui.main_container = ui.column().classes(
            'w-full min-h-[500px] bg-white'
        )
        settings_dialog = app_ui.build_settings_dialog()

        with ui.row().classes('absolute top-2 right-3 sm:top-3 sm:right-4'):
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
    start_app()