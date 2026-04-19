import time
import re
import logging
from typing import Optional
from urllib.parse import urlparse

from config_manager import ConfigManager
from anki_client import AnkiClient, AnkiConnectError
from deck_coordinator import DeckCoordinator, get_coordinator, new_session_id
from utils import download_image_as_base64

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
    """Manages the application state and business logic without UI dependencies.

    Each browser session creates its own ``CardManagerLogic``. The actual
    queue of cards to process lives in a shared :class:`DeckCoordinator` that
    hands out per-note leases, so concurrent sessions never work on the same
    card. See ``deck_coordinator.py`` for the full design.

    When used without ``load_deck`` (e.g. in unit tests that construct the
    manager and set ``current_note`` directly), the coordinator stays
    ``None`` and the class falls back to a simple index-based walk over
    ``self.valid_notes``. This keeps legacy code paths intact.
    """

    def __init__(
        self,
        config: ConfigManager,
        anki: AnkiClient,
        *,
        session_id: Optional[str] = None,
    ):
        self.config = config
        self.anki = anki
        self.session_id = session_id or new_session_id()

        self.coord: Optional[DeckCoordinator] = None
        self.deck_name: Optional[str] = None

        self.valid_notes = []   # Populated after load_deck; snapshot of what the
                                # coordinator knew at load time. Used by the UI
                                # "is anything loaded?" check and by tests.
        self.current_index = -1  # Legacy fallback index (tests only).
        self.current_note = None
        self.current_term = ""
        self.current_old_image_b64 = None

        self.field_term = self.config.get("DEFAULT_FIELD_SEARCH")
        self.field_image = self.config.get("DEFAULT_FIELD_IMAGE")
        self.field_source = self.config.get("DEFAULT_FIELD_SOURCE")
        self.tag_auto_replaced = self.config.get("DEFAULT_TAG")
        self.count = self.config.get_int("DEFAULT_IMAGES_PER_TERM")

    def _note_has_image_fields(self, fields: dict) -> bool:
        """True if this note type defines the image + source fields we write to."""
        return self.field_image in fields and self.field_source in fields

    async def _scan_deck_for_candidates(self, deck_name: str) -> list[dict]:
        """
        Talk to AnkiConnect, return the filtered list of notes that need images.

        Two fast steps:
          1. ``find_notes`` — IDs for the full deck filter.
          2. ``notesInfo`` for all IDs at once — one HTTP call instead of N.

        Pre-filtered in Python (no per-card HTTP round-trips). Raises
        :class:`AnkiConnectError` on any Anki failure so the caller can map
        it to a user-facing message.
        """
        logger.info("Scanning deck: %s", deck_name)
        t = self.tag_auto_replaced
        query = f'deck:"{deck_name}" -tag:{t} -tag:Finished'
        all_ids = await self.anki.find_notes(query)
        if not all_ids:
            return []

        logger.info("Fetching info for %d candidates in one batch...", len(all_ids))
        all_notes = await self.anki.get_notes_info(all_ids)

        valid: list[dict] = []
        skipped_wrong_model = 0
        for note in all_notes:
            fields = note['fields']
            if not self._note_has_image_fields(fields):
                skipped_wrong_model += 1
                continue
            raw_term = fields.get(self.field_term, {}).get('value', '')
            term = raw_term.split('<')[0].strip()
            if not term:
                continue  # empty search term — nothing to search for
            valid.append(note)

        if skipped_wrong_model:
            logger.info(
                "Skipped %s notes (note type has no '%s' and/or '%s' field).",
                skipped_wrong_model,
                self.field_image,
                self.field_source,
            )

        valid.sort(key=lambda n: n['noteId'])
        return valid

    async def load_deck(self, deck_name):
        """
        Scan the deck and register results with the shared coordinator.

        Safe to call multiple times — on re-load we release any lease this
        session was holding and merge newly-found notes into the coordinator
        without disturbing leases held by other sessions.
        """
        # If we're re-loading (e.g. same session picks a deck again), make
        # sure we don't keep a stale lease from the previous round.
        await self.release_current_lease(completed=False)

        try:
            valid_notes = await self._scan_deck_for_candidates(deck_name)
        except AnkiConnectError as e:
            logger.error("AnkiConnect error while scanning deck: %s", e)
            return False, f"Could not scan deck (Anki error): {e}"

        # Keep a per-session snapshot (used by UI/tests for the "anything
        # loaded?" check). The real queue lives in the coordinator.
        self.valid_notes = list(valid_notes)
        self.current_index = -1

        if not valid_notes:
            # Preserve historical wording so existing users see the same text.
            # Distinguishing "no cards at all" vs "all already done" would
            # require a second Anki query; not worth it.
            return False, f"No cards found (or all skipped) in '{deck_name}'"

        self.deck_name = deck_name
        self.coord = await get_coordinator(deck_name)
        added = await self.coord.update_queue(valid_notes)
        logger.info(
            "%d cards need images in '%s' (%d newly added to shared queue).",
            len(valid_notes), deck_name, added,
        )
        return True, f"Found {len(valid_notes)} cards to process."

    def is_finished(self):
        """Legacy check: True when the coordinator-less walk is exhausted."""
        return self.current_index >= len(self.valid_notes)

    async def advance_to_next_valid_card(self):
        """
        Move on to the next card this session is allowed to work on.

        With a coordinator attached (production path), ask for a fresh lease.
        Without one (unit tests), fall back to the pre-coord index walk over
        ``self.valid_notes``. Returns ``False`` when no card is available.
        """
        if self.coord is not None:
            next_note = await self.coord.lease_next(self.session_id)
            if next_note is None:
                self.current_note = None
                self.current_term = ""
                self.current_old_image_b64 = None
                return False
            self.current_note = next_note
        else:
            # Legacy path, kept so unit tests that prepopulate ``valid_notes``
            # and ``current_index`` keep working exactly as before.
            self.current_index += 1
            if self.is_finished():
                return False
            self.current_note = self.valid_notes[self.current_index]

        fields = self.current_note['fields']
        raw_term = fields.get(self.field_term, {}).get('value', '')
        self.current_term = raw_term.split('<')[0].strip()

        # Fetch the existing image preview (still one HTTP call per card,
        # but only for cards we're actually about to show).
        self.current_old_image_b64 = None
        old_img_html = fields.get(self.field_image, {}).get('value', '')
        match = re.search(r'src="([^"]+)"', old_img_html)
        if match:
            filename = match.group(1)
            b64_data = await self.anki.get_media_file_base64(filename)
            if b64_data:
                self.current_old_image_b64 = _data_url_for_anki_media_filename(
                    filename, b64_data
                )

        return True

    async def release_current_lease(self, *, completed: bool = False) -> None:
        """Release the coordinator lease (if any) on ``current_note``."""
        if self.coord is None or not self.current_note:
            return
        note_id = self.current_note.get("noteId")
        if note_id is None:
            return
        await self.coord.release(self.session_id, note_id, completed=completed)

    async def release_session_leases(self) -> int:
        """Drop every lease this session holds (tab close, etc)."""
        if self.coord is None:
            return 0
        return await self.coord.release_all_for(self.session_id)

    async def heartbeat(self) -> int:
        """Refresh TTL on all of this session's leases."""
        if self.coord is None:
            return 0
        return await self.coord.heartbeat(self.session_id)

    async def skip_card(self):
        """Adds auto-skipped tag to the current note and releases the lease."""
        if not self.current_note:
            return

        note_id = self.current_note['noteId']
        term = self.current_term

        await self.anki.add_tags([note_id], f"{self.tag_auto_replaced}::Skipped")
        if self.coord is not None:
            await self.coord.release(self.session_id, note_id, completed=True)
            self.coord.record_skipped()
        logger.info(f"Skipped '{term}'")
        return term

    async def ok_card(self):
        """Adds OK tag to the current note (image accepted as-is, no replacement)."""
        if not self.current_note:
            return

        note_id = self.current_note['noteId']
        term = self.current_term

        await self.anki.add_tags([note_id], f"{self.tag_auto_replaced}::OK")
        if self.coord is not None:
            await self.coord.release(self.session_id, note_id, completed=True)
            self.coord.record_replaced()
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
        if self.coord is not None:
            await self.coord.release(self.session_id, note_id, completed=True)
            self.coord.record_replaced()
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

        On success the coordinator lease on this note is released as completed
        (the note is removed from the shared queue). On any failure the lease
        is released as *not* completed so another session — or this one on a
        later retry — can pick the card back up.

        Returns the card's search-field text (plain) for logging and
        notifications, or the passed ``term`` if that field is empty.
        """
        # Use explicitly passed values — never rely on self.current_note here,
        # because by the time a background task runs, it may have changed.
        note = note or self.current_note
        term = term or self.current_term

        if not note:
            raise ActionError("No card to update.")

        note_id = note['noteId']

        try:
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

            # Filename uses the card's configured search field from the note
            # (e.g. English), not the live search box text — so editing the
            # query does not change the stem.
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

            await self.anki.update_note_fields(note_id, update_fields)

            tags_to_add = [f"{self.tag_auto_replaced}::{provider}"]
            await self.anki.add_tags([note_id], " ".join(tags_to_add))
        except BaseException:
            # Any failure — return the card to the shared pool so another
            # session can retry. Lease would expire anyway, but releasing
            # promptly keeps throughput high when multiple users are working.
            if self.coord is not None:
                try:
                    await self.coord.release(
                        self.session_id, note_id, completed=False
                    )
                except Exception:
                    logger.exception(
                        "Failed to release lease on note %d after error", note_id
                    )
            raise

        # Success path — lease goes away, note leaves the queue for good.
        if self.coord is not None:
            await self.coord.release(self.session_id, note_id, completed=True)
            self.coord.record_replaced()

        # Logs / UI: use the card's search-field text, not the edited search-box query.
        if stem_from_card:
            return stem_from_card
        return term or ""

    def get_remaining_count(self):
        """Number of un-leased cards left in the shared queue (for the status bar)."""
        if self.coord is not None:
            return self.coord.leasable_count()
        # Legacy fallback for tests that don't use a coordinator.
        return max(0, len(self.valid_notes) - self.current_index)

    def get_active_user_count(self) -> int:
        """How many distinct sessions currently hold a lease on this deck."""
        if self.coord is None:
            return 1 if self.current_note else 0
        return len(self.coord.active_sessions())
