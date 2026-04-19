import pytest
from unittest.mock import MagicMock, AsyncMock
import core
import deck_coordinator
from core import ActionError


def test_sanitize_filename_stem_and_provider_slug():
    assert core._sanitize_filename_stem("Amount") == "amount"
    assert core._sanitize_filename_stem("Thanks (Very colloquial)") == "thanks_very_colloquial"
    assert core._filename_provider_slug("Pexels") == "pexels"
    assert core._filename_provider_slug("Wikimedia") == "wikimedia"


def test_file_extension_from_url():
    assert core._file_extension_from_url("https://x.org/a.JPG") == "jpg"
    assert core._file_extension_from_url("https://x.org/icon.svg") == "svg"
    assert core._file_extension_from_url("https://x.org/p.png") == "png"


def test_data_url_for_anki_media_filename():
    s = core._data_url_for_anki_media_filename("card.svg", "QUJD")
    assert s.startswith("data:image/svg+xml;base64,")
    assert core._data_url_for_anki_media_filename("x.jpeg", "QQ").startswith(
        "data:image/jpeg;base64,"
    )

@pytest.fixture
def mock_anki_client():
    mock = AsyncMock()
    return mock

@pytest.fixture
def card_logic_manager(mock_config, mock_anki_client):
    return core.CardManagerLogic(mock_config, mock_anki_client)

@pytest.mark.asyncio
async def test_card_manager_init(card_logic_manager):
    assert card_logic_manager.current_index == -1

@pytest.mark.asyncio
async def test_card_manager_load_deck_no_cards(card_logic_manager):
    """Test behavior when no cards are found in the deck."""
    card_logic_manager.anki.find_notes = AsyncMock(return_value=[])
    
    success, msg = await card_logic_manager.load_deck("Test Deck")
    
    card_logic_manager.anki.find_notes.assert_called_once_with(
        'deck:"Test Deck" -tag:Replaced -tag:Finished'
    )
    
    assert not success
    assert "No cards found" in msg


@pytest.mark.asyncio
async def test_load_deck_skips_notes_without_image_fields(card_logic_manager, mock_anki_client):
    """Notes whose type lacks Image / Image Source must not appear in the queue."""
    mock_anki_client.find_notes = AsyncMock(return_value=[1, 2])
    mock_anki_client.get_notes_info = AsyncMock(
        return_value=[
            {
                "noteId": 1,
                "fields": {
                    "English": {"value": "keep"},
                    "Image": {"value": ""},
                    "Image Source": {"value": ""},
                },
            },
            {
                "noteId": 2,
                "fields": {
                    "English": {"value": "wrong model"},
                },
            },
        ]
    )

    success, msg = await card_logic_manager.load_deck("My Deck")
    assert success
    assert len(card_logic_manager.valid_notes) == 1
    assert card_logic_manager.valid_notes[0]["noteId"] == 1
    assert "Found 1 cards" in msg


@pytest.mark.asyncio
async def test_card_manager_advance_to_next_valid_card_end_of_list(card_logic_manager):
    """Test behavior when all cards have been processed."""
    card_logic_manager.note_ids = [123]
    card_logic_manager.current_index = 0  # One past the end (is_finished checks >= len)
    
    found = await card_logic_manager.advance_to_next_valid_card()
    
    assert not found

@pytest.mark.asyncio
async def test_card_manager_skip_card(card_logic_manager):
    """Test that skip card adds the tag and returns the term."""
    card_logic_manager.current_note = {"noteId": 999}
    card_logic_manager.current_term = "TestTerm"
    card_logic_manager.note_ids = [999]
    card_logic_manager.current_index = 0
    
    card_logic_manager.anki.add_tags = AsyncMock(return_value=None)
    
    term = await card_logic_manager.skip_card()
    
    card_logic_manager.anki.add_tags.assert_awaited_once_with([999], "Replaced::Skipped")
    assert term == "TestTerm"


@pytest.mark.asyncio
async def test_card_manager_ok_card(card_logic_manager):
    """Test that OK adds the tag and returns the term."""
    card_logic_manager.current_note = {"noteId": 999}
    card_logic_manager.current_term = "TestTerm"
    card_logic_manager.note_ids = [999]
    card_logic_manager.current_index = 0

    card_logic_manager.anki.add_tags = AsyncMock(return_value=None)

    term = await card_logic_manager.ok_card()

    card_logic_manager.anki.add_tags.assert_awaited_once_with([999], "Replaced::OK")
    assert term == "TestTerm"


@pytest.mark.asyncio
async def test_card_manager_unset_image(card_logic_manager):
    card_logic_manager.current_note = {
        "noteId": 999,
        "fields": {
            "English": {"value": "Term"},
            "Image": {"value": '<img src="x.jpg">'},
            "Image Source": {"value": "https://example.com/src"},
        },
    }
    card_logic_manager.current_term = "Term"

    card_logic_manager.anki.update_note_fields = AsyncMock(return_value=None)
    card_logic_manager.anki.add_tags = AsyncMock(return_value=None)

    term = await card_logic_manager.unset_image()

    card_logic_manager.anki.update_note_fields.assert_awaited_once_with(
        999, {"Image": "", "Image Source": ""}
    )
    card_logic_manager.anki.add_tags.assert_awaited_once_with([999], "Replaced::Unset")
    assert term == "Term"


@pytest.mark.asyncio
async def test_card_manager_unset_image_requires_image_fields(card_logic_manager):
    card_logic_manager.current_note = {
        "noteId": 1,
        "fields": {"English": {"value": "a"}},
    }
    card_logic_manager.current_term = "a"

    with pytest.raises(ActionError):
        await card_logic_manager.unset_image()


@pytest.mark.asyncio
async def test_card_manager_apply_image_to_card(card_logic_manager, monkeypatch):
    """Test that applying an image updates the card correctly."""
    note = {
        "noteId": 555,
        "fields": {
            "English": {"value": "Dog"},
            "Image": {"value": ""},
            "Image Source": {"value": ""},
        },
    }
    card_logic_manager.current_note = note
    card_logic_manager.current_term = "edited search query"
    card_logic_manager.note_ids = [555]
    card_logic_manager.current_index = 0
    
    img_data = {
        'full': 'http://fake.url/img.jpg',
        'provider': 'Pexels',
        'context_url': 'http://fake.url/context'
    }
    
    monkeypatch.setattr("core.download_image_as_base64", AsyncMock(return_value="fake_base64_data"))
    monkeypatch.setattr(core.time, 'time', lambda: 1234567890)
    
    card_logic_manager.anki.store_media_file = AsyncMock(return_value="dog_pexels_1234567890.jpg")
    card_logic_manager.anki.update_note_fields = AsyncMock(return_value=None)
    card_logic_manager.anki.add_tags = AsyncMock(return_value=None)
    
    # Filename stem and return value come from note field "English", not the edited search box.
    ret = await card_logic_manager.apply_image_to_card(img_data)
    assert ret == "Dog"

    expected_filename = "dog_pexels_1234567890.jpg"
    card_logic_manager.anki.store_media_file.assert_awaited_once_with(expected_filename, "fake_base64_data")
    card_logic_manager.anki.update_note_fields.assert_awaited_once()
    card_logic_manager.anki.add_tags.assert_awaited_once()


@pytest.mark.asyncio
async def test_two_sessions_share_coordinator_and_never_get_same_card(
    mock_config, monkeypatch
):
    """Two CardManagerLogic instances over the same deck must see different
    cards from advance_to_next_valid_card — that's the whole point of the
    shared coordinator."""
    anki_a = AsyncMock()
    anki_b = AsyncMock()

    # Both sessions scan and see the same three cards.
    scan_result = [
        {
            "noteId": nid,
            "fields": {
                "English": {"value": f"word-{nid}"},
                "Image": {"value": ""},
                "Image Source": {"value": ""},
            },
        }
        for nid in (10, 20, 30)
    ]
    anki_a.find_notes = AsyncMock(return_value=[n["noteId"] for n in scan_result])
    anki_a.get_notes_info = AsyncMock(return_value=scan_result)
    anki_b.find_notes = AsyncMock(return_value=[n["noteId"] for n in scan_result])
    anki_b.get_notes_info = AsyncMock(return_value=scan_result)
    # No prior image → nothing to fetch as preview.
    anki_a.get_media_file_base64 = AsyncMock(return_value=None)
    anki_b.get_media_file_base64 = AsyncMock(return_value=None)

    logic_a = core.CardManagerLogic(mock_config, anki_a, session_id="A")
    logic_b = core.CardManagerLogic(mock_config, anki_b, session_id="B")

    ok_a, _ = await logic_a.load_deck("Shared Deck")
    ok_b, _ = await logic_b.load_deck("Shared Deck")
    assert ok_a and ok_b
    assert logic_a.coord is logic_b.coord  # same shared coordinator

    got_a = []
    got_b = []
    # Alternate advances between sessions until the pool is empty.
    while True:
        a = await logic_a.advance_to_next_valid_card()
        b = await logic_b.advance_to_next_valid_card()
        if a:
            got_a.append(logic_a.current_note["noteId"])
        if b:
            got_b.append(logic_b.current_note["noteId"])
        if not a and not b:
            break

    assert sorted(got_a + got_b) == [10, 20, 30]
    assert set(got_a).isdisjoint(set(got_b))


@pytest.mark.asyncio
async def test_skip_card_releases_coordinator_lease(mock_config):
    """After skipping, the card must leave the shared queue entirely."""
    anki = AsyncMock()
    notes = [
        {
            "noteId": nid,
            "fields": {
                "English": {"value": f"w{nid}"},
                "Image": {"value": ""},
                "Image Source": {"value": ""},
            },
        }
        for nid in (1, 2)
    ]
    anki.find_notes = AsyncMock(return_value=[n["noteId"] for n in notes])
    anki.get_notes_info = AsyncMock(return_value=notes)
    anki.get_media_file_base64 = AsyncMock(return_value=None)
    anki.add_tags = AsyncMock(return_value=None)

    logic = core.CardManagerLogic(mock_config, anki, session_id="only")
    await logic.load_deck("Single User Deck")
    assert await logic.advance_to_next_valid_card()
    nid = logic.current_note["noteId"]

    await logic.skip_card()

    # Lease released + note removed from the shared queue.
    assert logic.coord.active_lease_count() == 0
    assert logic.coord.queue_size() == 1  # only the remaining one left


@pytest.mark.asyncio
async def test_apply_image_failure_returns_card_to_pool(mock_config, monkeypatch):
    """A download failure must not strand the card — another session should
    be able to pick it up."""
    anki = AsyncMock()
    notes = [
        {
            "noteId": 42,
            "fields": {
                "English": {"value": "dog"},
                "Image": {"value": ""},
                "Image Source": {"value": ""},
            },
        }
    ]
    anki.find_notes = AsyncMock(return_value=[42])
    anki.get_notes_info = AsyncMock(return_value=notes)
    anki.get_media_file_base64 = AsyncMock(return_value=None)
    # Simulate a failed download (returns None).
    monkeypatch.setattr("core.download_image_as_base64", AsyncMock(return_value=None))

    logic_a = core.CardManagerLogic(mock_config, anki, session_id="A")
    await logic_a.load_deck("Retry Deck")
    await logic_a.advance_to_next_valid_card()

    with pytest.raises(ActionError):
        await logic_a.apply_image_to_card(
            {"full": "http://x/y.jpg", "provider": "Pexels", "context_url": "http://x"}
        )

    # Card is back in the pool — session B can lease it.
    logic_b = core.CardManagerLogic(mock_config, anki, session_id="B")
    await logic_b.load_deck("Retry Deck")
    assert await logic_b.advance_to_next_valid_card()
    assert logic_b.current_note["noteId"] == 42


@pytest.mark.asyncio
async def test_release_session_leases_returns_cards_when_tab_closes(mock_config):
    anki = AsyncMock()
    notes = [
        {
            "noteId": nid,
            "fields": {
                "English": {"value": f"w{nid}"},
                "Image": {"value": ""},
                "Image Source": {"value": ""},
            },
        }
        for nid in (1, 2)
    ]
    anki.find_notes = AsyncMock(return_value=[1, 2])
    anki.get_notes_info = AsyncMock(return_value=notes)
    anki.get_media_file_base64 = AsyncMock(return_value=None)

    logic = core.CardManagerLogic(mock_config, anki, session_id="tab1")
    await logic.load_deck("Close Test Deck")
    await logic.advance_to_next_valid_card()
    assert logic.coord.active_lease_count() == 1

    released = await logic.release_session_leases()
    assert released == 1
    assert logic.coord.active_lease_count() == 0
    assert logic.coord.leasable_count() == 2


@pytest.mark.asyncio
async def test_card_manager_apply_image_svg_uses_svg_filename(card_logic_manager, monkeypatch):
    note = {
        "noteId": 777,
        "fields": {
            "English": {"value": "Icon"},
            "Image": {"value": ""},
            "Image Source": {"value": ""},
        },
    }
    card_logic_manager.current_note = note
    card_logic_manager.current_term = "Icon"

    img_data = {
        "full": "https://upload.wikimedia.org/wikipedia/commons/0/00/Example.svg",
        "provider": "Wikimedia",
        "context_url": "https://commons.wikimedia.org/wiki/File:Example.svg",
        "media_ext": "svg",
    }

    monkeypatch.setattr("core.download_image_as_base64", AsyncMock(return_value="c3ZnCg=="))
    monkeypatch.setattr(core.time, "time", lambda: 999)

    card_logic_manager.anki.store_media_file = AsyncMock(return_value=None)
    card_logic_manager.anki.update_note_fields = AsyncMock(return_value=None)
    card_logic_manager.anki.add_tags = AsyncMock(return_value=None)

    await card_logic_manager.apply_image_to_card(img_data)

    fname = card_logic_manager.anki.store_media_file.call_args[0][0]
    assert fname.endswith(".svg")
    assert fname.startswith("icon_wikimedia_")
