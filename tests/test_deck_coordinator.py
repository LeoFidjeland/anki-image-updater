"""Tests for the shared per-deck coordinator.

These exercise the exclusivity guarantees that enable safe concurrent use
from multiple browser sessions (iPad + laptop + desktop, etc.).
"""

import asyncio
import time

import pytest

import deck_coordinator
from deck_coordinator import DeckCoordinator, get_coordinator


def _note(note_id: int) -> dict:
    return {"noteId": note_id, "fields": {"English": {"value": f"word-{note_id}"}}}


@pytest.mark.asyncio
async def test_update_queue_adds_notes_and_dedupes():
    c = DeckCoordinator("deck")
    added = await c.update_queue([_note(1), _note(2), _note(3)])
    assert added == 3
    assert c.queue_size() == 3
    # Re-adding the same notes is a no-op; only new IDs get appended.
    added = await c.update_queue([_note(2), _note(3), _note(4)])
    assert added == 1
    assert c.queue_size() == 4


@pytest.mark.asyncio
async def test_lease_next_is_exclusive_across_sessions():
    """Two sessions must never receive the same note."""
    c = DeckCoordinator("deck")
    await c.update_queue([_note(i) for i in range(5)])

    got_a, got_b = [], []
    for _ in range(3):
        got_a.append((await c.lease_next("A"))["noteId"])
    for _ in range(2):
        got_b.append((await c.lease_next("B"))["noteId"])

    # All distinct IDs — no card handed to both sessions.
    assert len(set(got_a) | set(got_b)) == 5
    assert not (set(got_a) & set(got_b))
    # Queue is exhausted now.
    assert await c.lease_next("A") is None


@pytest.mark.asyncio
async def test_release_completed_removes_note_permanently():
    c = DeckCoordinator("deck")
    await c.update_queue([_note(1), _note(2)])
    n = await c.lease_next("A")
    assert n["noteId"] == 1

    await c.release("A", 1, completed=True)

    # 1 is gone; next lease is 2.
    nxt = await c.lease_next("A")
    assert nxt["noteId"] == 2
    # Re-adding note 1 via update_queue shouldn't resurrect it.
    added = await c.update_queue([_note(1)])
    assert added == 0


@pytest.mark.asyncio
async def test_release_not_completed_returns_card_to_pool():
    c = DeckCoordinator("deck")
    await c.update_queue([_note(1)])
    n = await c.lease_next("A")
    assert n["noteId"] == 1

    await c.release("A", 1, completed=False)

    # A fresh session can lease the same note again.
    again = await c.lease_next("B")
    assert again["noteId"] == 1


@pytest.mark.asyncio
async def test_release_ignores_lease_owned_by_another_session():
    c = DeckCoordinator("deck")
    await c.update_queue([_note(1)])
    await c.lease_next("A")

    # B tries to release A's lease — must be a no-op.
    await c.release("B", 1, completed=True)

    # A still owns the lease; next session can't lease it.
    assert await c.lease_next("B") is None
    # But A can still release it cleanly.
    await c.release("A", 1, completed=True)
    assert c.queue_size() == 0


@pytest.mark.asyncio
async def test_release_all_for_frees_every_lease_that_session_holds():
    c = DeckCoordinator("deck")
    await c.update_queue([_note(i) for i in range(4)])
    await c.lease_next("A")
    await c.lease_next("A")
    await c.lease_next("B")

    released = await c.release_all_for("A")
    assert released == 2
    # B's lease is untouched (1 of 4 still leased); the other 3 are leasable.
    assert c.leasable_count() == 3
    assert c.active_lease_count() == 1


@pytest.mark.asyncio
async def test_heartbeat_extends_ttl_only_for_owning_session():
    c = DeckCoordinator("deck", lease_ttl_s=0.05)
    await c.update_queue([_note(1)])
    await c.lease_next("A")

    # Just before expiry, A heartbeats — lease should survive.
    await asyncio.sleep(0.03)
    refreshed = await c.heartbeat("A")
    assert refreshed == 1
    await asyncio.sleep(0.03)
    # Still A's card.
    assert await c.lease_next("B") is None


@pytest.mark.asyncio
async def test_stale_leases_auto_expire_on_next_lease_call():
    c = DeckCoordinator("deck", lease_ttl_s=0.05)
    await c.update_queue([_note(1)])
    await c.lease_next("A")

    # A goes away without releasing; TTL elapses.
    await asyncio.sleep(0.1)
    # B asks for a card — A's stale lease is reaped and B gets the note.
    nxt = await c.lease_next("B")
    assert nxt["noteId"] == 1
    assert c.active_lease_count() == 1
    assert "B" in c.active_sessions()


@pytest.mark.asyncio
async def test_leasable_count_vs_queue_size():
    c = DeckCoordinator("deck")
    await c.update_queue([_note(i) for i in range(3)])
    await c.lease_next("A")
    assert c.queue_size() == 3          # total unfinished
    assert c.leasable_count() == 2       # what's still hand-out-able
    assert c.active_lease_count() == 1


@pytest.mark.asyncio
async def test_get_coordinator_is_shared_per_deck():
    c1 = await get_coordinator("shared-deck")
    c2 = await get_coordinator("shared-deck")
    other = await get_coordinator("other-deck")
    assert c1 is c2
    assert c1 is not other


@pytest.mark.asyncio
async def test_concurrent_lease_next_never_hands_out_duplicates():
    """Hammer the coordinator from many concurrent callers."""
    c = DeckCoordinator("deck")
    n_cards = 50
    n_sessions = 8
    await c.update_queue([_note(i) for i in range(n_cards)])

    async def session(sid: str) -> list[int]:
        got = []
        while True:
            n = await c.lease_next(sid)
            if n is None:
                return got
            got.append(n["noteId"])

    results = await asyncio.gather(
        *(session(f"S{i}") for i in range(n_sessions))
    )
    flat = [nid for sub in results for nid in sub]
    # Every note leased exactly once, across all sessions.
    assert sorted(flat) == list(range(n_cards))
