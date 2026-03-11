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
        
        # We store these as standard properties now, extracted from Anki notes
        self.note_ids = []
        self.current_index = -1
        self.current_note = None
        self.current_term = ""
        self.current_old_image_b64 = None
        
        # Determine fields to use (fallback to defaults if arguments aren't strictly passed)
        self.field_term = self.config.get("DEFAULT_FIELD_SEARCH", "English")
        self.field_image = self.config.get("DEFAULT_FIELD_IMAGE", "Image")
        self.field_source = self.config.get("DEFAULT_FIELD_SOURCE", "Image Source")
        self.field_notes = self.config.get("DEFAULT_FIELD_NOTES", "Notes")
        self.tag_auto_replaced = self.config.get("DEFAULT_TAG", "auto-replaced")
        
        try:
            self.count = int(self.config.get("DEFAULT_IMAGES_PER_TERM", 6))
        except (ValueError, TypeError):
            self.count = 6

    def load_deck(self, deck_name):
        """Loads valid cards from a deck and starts processing."""
        logger.info(f"Scanning deck: {deck_name}")
        query = f'deck:"{deck_name}" -tag:auto-skipped'
        self.note_ids = self.anki.find_notes(query)
        
        if not self.note_ids:
            return False, f"No cards found (or all skipped/processed) in '{deck_name}'"
        
        self.current_index = -1
        # Call next_card manually after this inside the UI to advance logic
        return True, f"Found {len(self.note_ids)} candidates. Filtering..."

    def is_finished(self):
        """Returns True if there are no more cards to process."""
        return self.current_index >= len(self.note_ids)

    def advance_to_next_valid_card(self):
        """
        Advances the internal pointer until it finds a card that needs processing,
        or hits the end of the list. Returns True if a card was loaded, False if finished.
        """
        while True:
            self.current_index += 1
            if self.is_finished():
                return False
                
            note_id = self.note_ids[self.current_index]
            notes_info = self.anki.get_notes_info([note_id])
            if not notes_info:
                continue

            self.current_note = notes_info[0]
            fields = self.current_note['fields']
            
            # Check if Source field is already populated
            source_val = fields.get(self.field_source, {}).get('value', '').strip()
            if source_val:
                logger.info(f"Skipping {note_id}: Source already exists.")
                continue

            raw_term = fields.get(self.field_term, {}).get('value', '')
            self.current_term = raw_term.split('<')[0].strip()
            
            # Skip empty terms immediately
            if not self.current_term:
                logger.warning(f"Skipping empty term for ID {note_id}")
                continue

            # We found a valid card. Extract its current image if it exists.
            self.current_old_image_b64 = None
            old_img_html = fields.get(self.field_image, {}).get('value', '')
            match = re.search(r'src="([^"]+)"', old_img_html)
            if match:
                filename = match.group(1)
                b64_data = self.anki.get_media_file_base64(filename)
                if b64_data:
                    self.current_old_image_b64 = f"data:image/jpeg;base64,{b64_data}"

            return True

    def skip_card(self):
        """Adds auto-skipped tag to the current note and advances state."""
        if not self.current_note:
            return
            
        note_id = self.current_note['noteId']
        term = self.current_term
        tag = "auto-skipped"
        
        self.anki.add_tags([note_id], tag)
        logger.info(f"Skipped '{term}'")
        return term

    def apply_image_to_card(self, img_data):
        """
        Downloads the full-res image from the provider, pushes to Anki,
        updates fields, and adds tags.
        """
        url = img_data['full']
        provider = img_data['provider']
        clean_term = self.current_term
        
        image_b64 = download_image_as_base64(url)
        if not image_b64:
            raise ActionError("Failed to download image from the provider.")

        # Sanitize filenames a bit more strictly
        safe_term = re.sub(r'[^a-zA-Z0-9]', '', clean_term)[:20] 
        timestamp = int(time.time())
        filename = f"{provider}_{safe_term}_{timestamp}.jpg"

        res = self.anki.store_media_file(filename, image_b64)
        if res is None:
             # Depending on implementation, `store_media_file` returning None indicates an error
             logger.warning(f"Store media file may have failed for {filename}")

        new_source_content = img_data['context_url']
        new_image_content = f'<img src="{filename}">'

        update_fields = {
            self.field_image: new_image_content,
            self.field_source: new_source_content,
        }
        
        self.anki.update_note_fields(self.current_note['noteId'], update_fields)
        
        # Tags
        tags_to_add = [self.tag_auto_replaced, f"updated-{provider}"]
        self.anki.add_tags([self.current_note['noteId']], " ".join(tags_to_add))

        return clean_term

    def get_remaining_count(self):
        """Returns the number of cards left to process."""
        if self.current_index == -1:
             return len(self.note_ids)
        return max(0, len(self.note_ids) - self.current_index)
