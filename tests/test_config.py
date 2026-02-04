import os
from config_manager import ConfigManager

def test_defaults(mock_config):
    """Test that defaults are loaded correctly."""
    assert mock_config.get("DEFAULT_IMAGES_PER_TERM") == 6
    assert mock_config.get("DEFAULT_FIELD_SEARCH") == "English"

def test_set_and_get(mock_config):
    """Test setting and getting a value."""
    mock_config.set("TEST_KEY", "test_value")
    assert mock_config.get("TEST_KEY") == "test_value"

def test_persistence(mock_config):
    """Test that values persist to disk."""
    mock_config.set("PERSIST_KEY", "persistent_value")
    
    # Reload config from disk
    new_config = ConfigManager()
    assert new_config.get("PERSIST_KEY") == "persistent_value"

def test_env_override(mock_config, monkeypatch):
    """Test that environment variables override config values."""
    mock_config.set("PEXELS_API_KEY", "config_key")
    
    monkeypatch.setenv("PEXELS_API_KEY", "env_key")
    assert mock_config.get("PEXELS_API_KEY") == "env_key"
