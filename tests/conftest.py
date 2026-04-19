import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Ensure we can import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_manager import ConfigManager
import deck_coordinator


@pytest.fixture(autouse=True)
def _reset_deck_coordinator_registry():
    """Keep the shared-coordinator registry empty between tests so one
    test's fake deck never leaks into another test's assertions."""
    deck_coordinator.reset_registry()
    yield
    deck_coordinator.reset_registry()

@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Fixture to provide a ConfigManager using a temporary file."""
    monkeypatch.setattr("config_manager.user_config_dir", lambda app, author: str(tmp_path))
    cfg = ConfigManager()
    cfg._config = cfg.DEFAULT_CONFIG.copy()
    return cfg

@pytest.fixture
def real_config():
    """Fixture that loads the actual user configuration for integration tests."""
    return ConfigManager()

@pytest.fixture
def mock_httpx_get(monkeypatch):
    """Fixture to mock httpx.AsyncClient.get (used in search_providers and utils)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={})
    mock_response.content = b"fake_image_data"
    
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)
    return mock_client
