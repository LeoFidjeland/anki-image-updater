import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Ensure we can import from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from config_manager import ConfigManager

@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Fixture to provide a ConfigManager using a temporary file."""
    # Patch the user_config_dir to use tmp_path
    monkeypatch.setattr("config_manager.user_config_dir", lambda app, author: str(tmp_path))
    
    cfg = ConfigManager()
    # Reset to defaults for each test to be safe
    cfg._config = cfg.DEFAULT_CONFIG.copy()
    return cfg

@pytest.fixture
def real_config():
    """Fixture that loads the actual user configuration for integration tests."""
    return ConfigManager()

@pytest.fixture
def mock_requests_get(monkeypatch):
    """Fixture to mock requests.get"""
    mock = MagicMock()
    monkeypatch.setattr("requests.get", mock)
    return mock
