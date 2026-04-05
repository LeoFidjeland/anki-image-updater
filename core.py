import base64
import time
import re
import logging
from urllib.parse import urlparse

from config_manager import ConfigManager
from anki_client import AnkiClient, AnkiConnectError
from image_sizing import preview_dims_from_original
from utils import download_image_as_base64, parse_svg_aspect_dimensions

logger = logging.getLogger(__name__)

_MIME_BY_EXT = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _file_extension_from_url(url: str) -> str:
    """Infer stored filename extension from the download URL path (default ``jpg``)."""
    path = (urlparse(url or "").path or "").lower()
    if path.endswith(".svg"):
        return "svg"
    if path.endswith(".png"):
        return "png"
    if path.endswith(".gif"):
        return "gif"
    if path.endswith(".webp"):
        return "webp"
    if path.endswith(".jpeg"):
        return "jpeg"
    if path.endswith(".jpg"):
        return "jpg"
    return "jpg"


def _data_url_for_anki_media_filename(filename: str, b64_data: str) -> str:
    """Build a browser-correct data URI for Anki media (SVG is not ``image/jpeg``)."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    mime = _MIME_BY_EXT.get(ext, "image/jpeg")
    return f"data:{mime};base64,{b64_data}"


def _sanitize_filename_stem(text: str, max_len: int = 48) -> str:
    """
    Lowercase slug for a filesystem component: letters/digits (any script) and underscores.
    """
    s = (text or "").strip().lower()
    s = re.sub(r"[^\w]", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "image"
    return s[:max_len]


def _filename_provider_slug(provider_display: str) -> str:
    """Stable lowercase slug for img_data['provider'] (e.g. Pexels -> pexels)."""
    return re.sub(r"\s+", "_", (provider_display or "unknown").strip().lower())


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
        self.current_old_image_layout_dims = {}

        self.field_term = self.config.get("DEFAULT_FIELD_SEARCH")
        self.field_image = self.config.get("DEFAULT_FIELD_IMAGE")
        self.field_source = self.config.get("DEFAULT_FIELD_SOURCE")
        self.tag_auto_replaced = self.config.get("DEFAULT_TAG")
        self.count = self.config.get_int("DEFAULT_IMAGES_PER_TERM")

    def _note_has_image_fields(self, fields: dict) -> bool:
        """True if this note type defines the image + source fields we write to."""
        return self.field_image in fields and self.field_source in fields

    async def load_deck(self, deck_name):
        """
        Loads all cards from a deck in two fast steps:
        1. find_notes — get IDs (single fast query)
        2. notesInfo for ALL IDs at once — one HTTP call instead of N
        Then pre-filters in Python. This avoids per-card HTTP round-trips on startup.
        """
        logger.info(f"Scanning deck: {deck_name}")
        t = self.tag_auto_replaced
        query = f'deck:"{deck_name}" -tag:{t} -tag:Finished'
        try:
            all_ids = await self.anki.find_notes(query)
        except AnkiConnectError as e:
            logger.error("AnkiConnect error while finding notes: %s", e)
            return False, f"Could not scan deck (Anki error): {e}"

        if not all_ids:
            return False, f"No cards found (or all skipped) in '{deck_name}'"

        logger.info(f"Fetching info for {len(all_ids)} candidates in one batch...")
        try:
            all_notes = await self.anki.get_notes_info(all_ids)
        except AnkiConnectError as e:
            logger.error("AnkiConnect error while loading note info: %s", e)
            return False, f"Could not load note info (Anki error): {e}"

        # Pre-filter in Python — no more per-card HTTP calls during scan
        self.valid_notes = []
        skipped_wrong_model = 0
        for note in all_notes:
            fields = note['fields']
            if not self._note_has_image_fields(fields):
                skipped_wrong_model += 1
                continue
            source_val = fields.get(self.field_source, {}).get('value', '').strip()
            # if source_val:
                # continue  # already has an image source
            raw_term = fields.get(self.field_term, {}).get('value', '')
            term = raw_term.split('<')[0].strip()
            if not term:
                continue  # empty search term
            self.valid_notes.append(note)

        if skipped_wrong_model:
            logger.info(
                "Skipped %s notes (note type has no '%s' and/or '%s' field).",
                skipped_wrong_model,
                self.field_image,
                self.field_source,
            )

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
        self.current_old_image_layout_dims = {}
        old_img_html = fields.get(self.field_image, {}).get('value', '')
        match = re.search(r'src="([^"]+)"', old_img_html)
        if match:
            filename = match.group(1)
            b64_data = await self.anki.get_media_file_base64(filename)
            if b64_data:
                self.current_old_image_b64 = _data_url_for_anki_media_filename(
                    filename, b64_data
                )
                if filename.lower().endswith(".svg"):
                    try:
                        raw = base64.b64decode(b64_data).decode(
                            "utf-8", errors="replace"
                        )
                        parsed = parse_svg_aspect_dimensions(raw)
                        if parsed:
                            ow, oh = parsed
                            self.current_old_image_layout_dims = (
                                preview_dims_from_original(ow, oh)
                            )
                    except Exception:
                        logger.debug(
                            "Could not infer SVG preview aspect ratio",
                            exc_info=True,
                        )

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

    async def ok_card(self):
        """Adds OK tag to the current note (image accepted as-is, no replacement)."""
        if not self.current_note:
            return

        note_id = self.current_note['noteId']
        term = self.current_term

        await self.anki.add_tags([note_id], f"{self.tag_auto_replaced}::OK")
        logger.info(f"Marked OK '{term}'")
        return term

    async def unset_image(self):
        """Clears image + source fields and adds Unset tag."""
        if not self.current_note:
            return

        note_id = self.current_note['noteId']
        term = self.current_term
        nf = self.current_note.get("fields") or {}

        if not self._note_has_image_fields(nf):
            raise ActionError(
                f"This note type has no '{self.field_image}' and/or '{self.field_source}' "
                "field — cannot unset. Check Settings field names."
            )

        await self.anki.update_note_fields(
            note_id,
            {self.field_image: "", self.field_source: ""},
        )
        await self.anki.add_tags([note_id], f"{self.tag_auto_replaced}::Unset")
        logger.info(f"Unset image for '{term}'")
        return term

    async def apply_image_to_card(self, img_data, *, note=None, term=None):
        """
        Downloads the full-res image from the provider, pushes to Anki,
        updates fields, and adds tags.

        Media filename: ``{stem}_{provider}_{unix_timestamp}.{ext}`` (*ext* from URL or
        ``img_data['media_ext']``, default ``jpg``) where *stem* comes from
        the note's configured search field (``field_term``), not the live search-box text.
        The trailing number is Unix time in seconds so re-saves get unique names.

        `note` and `term` can be passed explicitly to avoid race conditions
        when the logic state has already advanced to the next card.

        Returns the card's search-field text (plain) for logging and notifications,
        or the passed ``term`` if that field is empty.
        """
        # Use explicitly passed values — never rely on self.current_note here,
        # because by the time a background task runs, it may have changed.
        note = note or self.current_note
        term = term or self.current_term
        
        if not note:
            raise ActionError("No card to update.")

        nf = note['fields']
        if not self._note_has_image_fields(nf):
            raise ActionError(
                f"This note type has no '{self.field_image}' and/or '{self.field_source}' "
                "field — cannot save the image. Check Settings field names or skip this card."
            )

        url = img_data['full']
        provider = img_data['provider']

        image_b64 = await download_image_as_base64(url)
        if not image_b64:
            raise ActionError("Failed to download image from the provider.")

        ext = (img_data.get("media_ext") or "").strip().lower().lstrip(".")
        if not ext:
            ext = _file_extension_from_url(url)

        # Filename uses the card's configured search field from the note (e.g. English),
        # not the live search box text — so editing the query does not change the stem.
        raw_from_note = note['fields'].get(self.field_term, {}).get('value', '')
        stem_from_card = raw_from_note.split('<')[0].strip()
        stem = _sanitize_filename_stem(stem_from_card)
        provider_slug = _filename_provider_slug(provider)
        # Unix time (seconds) — keeps names unique when re-saving the same card.
        timestamp = int(time.time())
        filename = f"{stem}_{provider_slug}_{timestamp}.{ext}"

        await self.anki.store_media_file(filename, image_b64)

        new_source_content = img_data['context_url']
        new_image_content = f'<img src="{filename}">'

        update_fields = {
            self.field_image: new_image_content,
            self.field_source: new_source_content,
        }
        
        await self.anki.update_note_fields(note['noteId'], update_fields)
        
        tags_to_add = [f"{self.tag_auto_replaced}::{provider}"]
        await self.anki.add_tags([note['noteId']], " ".join(tags_to_add))

        # Logs / UI: use the card's search-field text, not the edited search-box query.
        if stem_from_card:
            return stem_from_card
        return term or ""

    def get_remaining_count(self):
        """Returns the number of cards left to process."""
        return max(0, len(self.valid_notes) - self.current_index)
