import pytest
from unittest.mock import MagicMock
import core

@pytest.fixture
def mock_anki_invoke(monkeypatch):
    mock = MagicMock()
    # We mock out the AnkiClient class methods used
    monkeypatch.setattr("anki_client.AnkiClient.invoke", mock)
    return mock

@pytest.fixture
def mock_anki_client():
    mock = MagicMock()
    return mock

@pytest.fixture
def card_logic_manager(mock_config, mock_anki_client):
    return core.CardManagerLogic(mock_config, mock_anki_client)

def test_card_manager_init(card_logic_manager):
    assert card_logic_manager.current_index == -1

def test_card_manager_load_deck_no_cards(card_logic_manager):
    """Test behavior when no cards are found in the deck."""
    card_logic_manager.anki.find_notes.return_value = []
    
    success, msg = card_logic_manager.load_deck("Test Deck")
    
    # Should call find_notes with the correct query
    card_logic_manager.anki.find_notes.assert_called_once_with('deck:"Test Deck" -tag:auto-skipped')
    
    assert not success
    assert "No cards found" in msg

def test_card_manager_advance_to_next_valid_card_end_of_list(card_logic_manager):
    """Test behavior when all cards have been processed."""
    card_logic_manager.note_ids = [123]
    card_logic_manager.current_index = 0 # Currently at the end
    
    # Call advance
    found = card_logic_manager.advance_to_next_valid_card()
    
    assert card_logic_manager.current_index == 1
    assert not found

def test_card_manager_skip_card(card_logic_manager):
    """Test that skip card adds the tag and returns the term."""
    card_logic_manager.current_note = {"noteId": 999}
    card_logic_manager.current_term = "TestTerm"
    card_logic_manager.note_ids = [999]
    card_logic_manager.current_index = 0
    
    term = card_logic_manager.skip_card()
    
    # Verify addTags was called
    card_logic_manager.anki.add_tags.assert_any_call([999], "auto-skipped")
    assert term == "TestTerm"

def test_card_manager_apply_image_to_card(card_logic_manager, monkeypatch):
    """Test that applying an image updates the card correctly."""
    # Fake state
    card_logic_manager.current_note = {"noteId": 555}
    card_logic_manager.current_term = "Dog"
    card_logic_manager.note_ids = [555]
    card_logic_manager.current_index = 0
    
    img_data = {
        'full': 'http://fake.url/img.jpg',
        'provider': 'pexels',
        'context_url': 'http://fake.url/context'
    }
    
    # Mock download
    monkeypatch.setattr("core.download_image_as_base64", lambda url: "fake_base64_data")
    # Mock time so filename is deterministic
    monkeypatch.setattr(core.time, 'time', lambda: 1234567890)
    
    card_logic_manager.apply_image_to_card(img_data)
    
    # Check store_media_file
    expected_filename = "pexels_Dog_1234567890.jpg"
    card_logic_manager.anki.store_media_file.assert_any_call(expected_filename, "fake_base64_data")
    
    # Check updateNoteFields
    card_logic_manager.anki.update_note_fields.assert_any_call(555, {
        "Image": f'<img src="{expected_filename}">',
        "Image Source": "http://fake.url/context"
    })
    
    # Check add_tags
    card_logic_manager.anki.add_tags.assert_any_call([555], "replaced-auto updated-pexels")
