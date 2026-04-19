"""
Shared per-deck queue of notes needing images.

Multiple browser sessions (LAN users on iPads, laptops, etc.) each get their
own ``CardManagerLogic``, but they all ask a single ``DeckCoordinator`` for
the next card to work on. The coordinator hands out exclusive *leases* so
no two sessions ever see the same card simultaneously. Leases expire
automatically if a user closes their tab, loses network, or just walks away,
so cards never get permanently stuck.

The whole thing runs inside NiceGUI's single asyncio event loop; a single
``asyncio.Lock`` per coordinator is enough to keep all state consistent.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL_S: float = 5 * 60
DEFAULT_HEARTBEAT_EVERY_S: float = 60


@dataclass
class Lease:
    note_id: int
    session_id: str
    expires_at: float


class DeckCoordinator:
    """
    Canonical queue + lease table for a single Anki deck.

    Lifecycle:
      1. ``update_queue(notes)`` — called on every deck load. Merges newly
         scanned notes into the queue without disturbing existing leases.
      2. ``lease_next(session_id)`` — atomic "give me the next card I'm
         allowed to work on". Never returns a note another session holds.
      3. ``release(session_id, note_id, completed=...)`` — either the card
         was processed (``completed=True``, remove from queue) or the user
         failed / bailed out (``completed=False``, return to pool).
      4. ``heartbeat(session_id)`` — extends all of this session's leases;
         call it on a timer while a browser tab is alive.
      5. ``release_all_for(session_id)`` — called on tab disconnect.

    Stale leases (where ``expires_at`` is in the past) are reaped on every
    ``lease_next`` call, so even without clean disconnects no card is lost.
    """

    def __init__(
        self,
        deck_name: str,
        *,
        lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
    ) -> None:
        self.deck_name = deck_name
        self.lease_ttl_s = lease_ttl_s

        self._queue: list[dict] = []            # notes still awaiting work (FIFO)
        self._known_ids: set[int] = set()       # every note we've ever seen
        self._done: set[int] = set()            # completed in this process lifetime
        self._leases: dict[int, Lease] = {}     # note_id -> Lease
        self._lock = asyncio.Lock()
        self._loaded = False

        self.stats_replaced = 0
        self.stats_skipped = 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def update_queue(self, notes: list[dict]) -> int:
        """
        Merge a freshly-scanned note list into the queue.

        Notes already in the queue, currently leased, or previously marked
        done are left untouched. Returns the number of *new* notes added.
        """
        async with self._lock:
            added = 0
            for note in notes:
                nid = note["noteId"]
                if nid in self._known_ids or nid in self._done:
                    continue
                self._queue.append(note)
                self._known_ids.add(nid)
                added += 1
            self._loaded = True
        if added:
            logger.info(
                "DeckCoordinator[%s]: added %d new card(s) to queue "
                "(queue size now %d)",
                self.deck_name, added, len(self._queue),
            )
        return added

    async def lease_next(self, session_id: str) -> Optional[dict]:
        """Return the next un-leased note for this session, or None."""
        async with self._lock:
            self._expire_stale_locked()
            for note in self._queue:
                nid = note["noteId"]
                if nid in self._leases:
                    continue
                self._leases[nid] = Lease(
                    note_id=nid,
                    session_id=session_id,
                    expires_at=time.time() + self.lease_ttl_s,
                )
                logger.debug(
                    "DeckCoordinator[%s]: session %s leased note %d",
                    self.deck_name, session_id, nid,
                )
                return note
            return None

    async def release(
        self,
        session_id: str,
        note_id: int,
        *,
        completed: bool,
    ) -> None:
        """
        Release this session's lease on ``note_id``.

        If ``completed`` is True, the note is also removed from the queue
        permanently (for this process lifetime). Otherwise it goes back
        into the pool for the next ``lease_next`` caller.

        A release for a note another session owns is ignored with a
        warning — never silently steal someone else's card.
        """
        async with self._lock:
            lease = self._leases.get(note_id)
            if lease is None:
                # Lease already expired / never existed. Still honour
                # `completed=True` so the queue reflects reality.
                if completed:
                    self._mark_done_locked(note_id)
                return
            if lease.session_id != session_id:
                logger.warning(
                    "DeckCoordinator[%s]: session %s tried to release "
                    "note %d owned by %s — ignoring",
                    self.deck_name, session_id, note_id, lease.session_id,
                )
                return
            del self._leases[note_id]
            if completed:
                self._mark_done_locked(note_id)

    def _mark_done_locked(self, note_id: int) -> None:
        self._done.add(note_id)
        self._queue = [n for n in self._queue if n["noteId"] != note_id]

    async def release_all_for(self, session_id: str) -> int:
        """Release every lease held by ``session_id`` (tab closed, etc)."""
        async with self._lock:
            released = [
                nid for nid, lease in self._leases.items()
                if lease.session_id == session_id
            ]
            for nid in released:
                del self._leases[nid]
        if released:
            logger.info(
                "DeckCoordinator[%s]: session %s disconnected, released %d lease(s)",
                self.deck_name, session_id, len(released),
            )
        return len(released)

    async def heartbeat(self, session_id: str) -> int:
        """Extend TTL for every lease held by ``session_id``."""
        async with self._lock:
            now = time.time()
            count = 0
            for lease in self._leases.values():
                if lease.session_id == session_id:
                    lease.expires_at = now + self.lease_ttl_s
                    count += 1
            return count

    def _expire_stale_locked(self) -> None:
        now = time.time()
        stale = [nid for nid, l in self._leases.items() if l.expires_at < now]
        for nid in stale:
            old = self._leases.pop(nid)
            logger.info(
                "DeckCoordinator[%s]: expiring stale lease on note %d "
                "(session %s, %.0fs overdue)",
                self.deck_name, nid, old.session_id, now - old.expires_at,
            )

    # ---- read-only introspection ------------------------------------------

    def queue_size(self) -> int:
        """Unfinished notes including those currently leased."""
        return len(self._queue)

    def leasable_count(self) -> int:
        """Unfinished notes NOT currently held by any session."""
        return max(0, len(self._queue) - len(self._leases))

    def active_lease_count(self) -> int:
        return len(self._leases)

    def active_sessions(self) -> set[str]:
        return {l.session_id for l in self._leases.values()}

    # ---- stats (shared across sessions) -----------------------------------

    def record_replaced(self) -> None:
        self.stats_replaced += 1

    def record_skipped(self) -> None:
        self.stats_skipped += 1


# ---------------------------------------------------------------------------
# Module-level registry: one coordinator per deck name, shared by all sessions
# ---------------------------------------------------------------------------

_registry: dict[str, DeckCoordinator] = {}
_registry_lock = asyncio.Lock()


async def get_coordinator(deck_name: str) -> DeckCoordinator:
    """Return (and lazily create) the shared coordinator for ``deck_name``."""
    async with _registry_lock:
        coord = _registry.get(deck_name)
        if coord is None:
            coord = DeckCoordinator(deck_name)
            _registry[deck_name] = coord
            logger.info("DeckCoordinator: created for deck '%s'", deck_name)
        return coord


def reset_registry() -> None:
    """Test hook — wipes every cached coordinator. Do not call in production."""
    _registry.clear()


def new_session_id() -> str:
    """Short opaque id for a browser session. Stable for the tab's lifetime."""
    return uuid.uuid4().hex
