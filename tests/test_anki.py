import pytest
from anki_client import AnkiClient

def check_anki_running():
    """Helper to check if AnkiConnect is running on localhost:8765."""
    try:
        import httpx
        r = httpx.post("http://localhost:8765", json={"action": "version", "version": 6}, timeout=2)
        r.raise_for_status()
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not check_anki_running(),
    reason="Anki must be running with AnkiConnect on localhost:8765 to run these integration tests."
)

@pytest.fixture
def anki():
    return AnkiClient()

@pytest.mark.asyncio
async def test_anki_invoke_deck_names(anki):
    """Tests basic connectivity by fetching deck names."""
    result = await anki.invoke("deckNames")
    assert isinstance(result, list)
    assert len(result) >= 1 

@pytest.mark.asyncio
async def test_anki_invoke_invalid_action(anki):
    """Tests error handling for invalid AnkiConnect actions."""
    result = await anki.invoke("someNonExistentActionForTesting")
    assert result is None
