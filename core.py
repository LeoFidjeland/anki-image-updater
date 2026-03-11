import time
import re
import logging
from config_manager import ConfigManager
from anki_client import AnkiClient
from utils import download_image_as_base64

logger = logging.getLogger(__name__)

class ActionError(Exception):
    """Exception raised for known logic errors that the user should see."""
    pass

class CardManagerLogic:
    """Manages the application state and business logic without UI dependencies."""

    def __init__(self, config: ConfigManager, anki: AnkiClient):
        self.config = config
        self.anki = anki
        
        self.valid_notes = []   # Pre-filtered list of notes that need images
        self.current_index = -1
        self.current_note = None
        self.current_term = ""
        self.current_old_image_b64 = None
        
        self.field_term = self.config.get("DEFAULT_FIELD_SEARCH", "English")
        self.field_image = self.config.get("DEFAULT_FIELD_IMAGE", "Image")
        self.field_source = self.config.get("DEFAULT_FIELD_SOURCE", "Image Source")
        self.tag_auto_replaced = self.config.get("DEFAULT_TAG", "Replaced")
        
        try:
            self.count = int(self.config.get("DEFAULT_IMAGES_PER_TERM", 6))
        except (ValueError, TypeError):
            self.count = 6

    async def load_deck(self, deck_name):
        """
        Loads all cards from a deck in two fast steps:
        1. find_notes — get IDs (single fast query)
        2. notesInfo for ALL IDs at once — one HTTP call instead of N
        Then pre-filters in Python. This avoids per-card HTTP round-trips on startup.
        """
        logger.info(f"Scanning deck: {deck_name}")
        query = f'deck:"{deck_name}" -tag:{self.tag_auto_replaced}::Skipped'
        all_ids = await self.anki.find_notes(query)
        
        if not all_ids:
            return False, f"No cards found (or all skipped) in '{deck_name}'"

        logger.info(f"Fetching info for {len(all_ids)} candidates in one batch...")
        all_notes = await self.anki.get_notes_info(all_ids)

        # Pre-filter in Python — no more per-card HTTP calls during scan
        self.valid_notes = []
        for note in all_notes:
            fields = note['fields']
            source_val = fields.get(self.field_source, {}).get('value', '').strip()
            if source_val:
                continue  # already has an image source
            raw_term = fields.get(self.field_term, {}).get('value', '')
            term = raw_term.split('<')[0].strip()
            if not term:
                continue  # empty search term
            self.valid_notes.append(note)

        if not self.valid_notes:
            return False, f"No cards needing images in '{deck_name}'"

        self.current_index = -1
        logger.info(f"{len(self.valid_notes)} cards need images.")
        return True, f"Found {len(self.valid_notes)} cards to process."

    def is_finished(self):
        """Returns True if there are no more cards to process."""
        return self.current_index >= len(self.valid_notes)

    async def advance_to_next_valid_card(self):
        """
        Advances to the next pre-filtered card. All filtering was done at load time,
        so this is now O(1) — just looks up the next note and fetches its image preview.
        """
        self.current_index += 1
        if self.is_finished():
            return False

        self.current_note = self.valid_notes[self.current_index]
        fields = self.current_note['fields']

        raw_term = fields.get(self.field_term, {}).get('value', '')
        self.current_term = raw_term.split('<')[0].strip()

        # Fetch the existing image preview (still one HTTP call per card, but only
        # for cards we're actually going to show — not for the thousands we're skipping)
        self.current_old_image_b64 = None
        old_img_html = fields.get(self.field_image, {}).get('value', '')
        match = re.search(r'src="([^"]+)"', old_img_html)
        if match:
            filename = match.group(1)
            b64_data = await self.anki.get_media_file_base64(filename)
            if b64_data:
                self.current_old_image_b64 = f"data:image/jpeg;base64,{b64_data}"

        return True

    async def skip_card(self):
        """Adds auto-skipped tag to the current note."""
        if not self.current_note:
            return
            
        note_id = self.current_note['noteId']
        term = self.current_term
        
        await self.anki.add_tags([note_id], f"{self.tag_auto_replaced}::Skipped")
        logger.info(f"Skipped '{term}'")
        return term

    async def apply_image_to_card(self, img_data, *, note=None, term=None):
        """
        Downloads the full-res image from the provider, pushes to Anki,
        updates fields, and adds tags.
        
        `note` and `term` can be passed explicitly to avoid race conditions
        when the logic state has already advanced to the next card.
        """
        # Use explicitly passed values — never rely on self.current_note here,
        # because by the time a background task runs, it may have changed.
        note = note or self.current_note
        term = term or self.current_term
        
        if not note:
            raise ActionError("No card to update.")

        url = img_data['full']
        provider = img_data['provider']
        
        image_b64 = await download_image_as_base64(url)
        if not image_b64:
            raise ActionError("Failed to download image from the provider.")

        safe_term = re.sub(r'[^a-zA-Z0-9]', '', term)[:20]
        timestamp = int(time.time())
        filename = f"{provider}_{safe_term}_{timestamp}.jpg"

        res = await self.anki.store_media_file(filename, image_b64)
        if res is None:
            logger.warning(f"Store media file may have failed for {filename}")

        new_source_content = img_data['context_url']
        new_image_content = f'<img src="{filename}">'

        update_fields = {
            self.field_image: new_image_content,
            self.field_source: new_source_content,
        }
        
        await self.anki.update_note_fields(note['noteId'], update_fields)
        
        tags_to_add = [f"{self.tag_auto_replaced}::{provider}"]
        await self.anki.add_tags([note['noteId']], " ".join(tags_to_add))

        return term

    def get_remaining_count(self):
        """Returns the number of cards left to process."""
        return max(0, len(self.valid_notes) - self.current_index)
