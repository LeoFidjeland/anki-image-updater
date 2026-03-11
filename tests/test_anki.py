import pytest
from anki_client import AnkiClient

def check_anki_running():
    """Helper to check if AnkiConnect is running on localhost:8765."""
    try:
        import requests
        r = requests.post("http://localhost:8765", json={"action": "version", "version": 6}, timeout=2)
        r.raise_for_status()
        return True
    except Exception:
        return False

# We mark these tests to be skipped if Anki is not running
pytestmark = pytest.mark.skipif(
    not check_anki_running(),
    reason="Anki must be running with AnkiConnect on localhost:8765 to run these integration tests."
)

@pytest.fixture
def anki():
    return AnkiClient()

def test_anki_invoke_deck_names(anki):
    """Tests basic connectivity by fetching deck names."""
    result = anki.invoke("deckNames")
    assert isinstance(result, list)
    # The default deck creation often leaves a 'Default' deck
    assert len(result) >= 1 

def test_anki_invoke_invalid_action(anki):
    """Tests error handling for invalid AnkiConnect actions."""
    # invoke returns None on error and logs it
    result = anki.invoke("someNonExistentActionForTesting")
    assert result is None
