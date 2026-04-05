import pytest
from unittest.mock import MagicMock, AsyncMock
import core
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
        'deck:"Test Deck" -tag:Replaced'
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
