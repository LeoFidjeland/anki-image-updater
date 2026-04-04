import os
from config_manager import ConfigManager


def test_defaults(mock_config):
    """Fresh config matches DEFAULT_CONFIG for built-in keys."""
    d = ConfigManager.DEFAULT_CONFIG
    assert mock_config.get("DEFAULT_IMAGES_PER_TERM") == d["DEFAULT_IMAGES_PER_TERM"]
    assert mock_config.get("DEFAULT_FIELD_SEARCH") == d["DEFAULT_FIELD_SEARCH"]

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


def test_get_falls_back_to_default_config_when_key_missing(mock_config):
    """Built-in keys resolve from DEFAULT_CONFIG if absent from _config."""
    del mock_config._config["DEFAULT_FIELD_SEARCH"]
    assert mock_config.get("DEFAULT_FIELD_SEARCH") == ConfigManager.DEFAULT_CONFIG["DEFAULT_FIELD_SEARCH"]


def test_get_int_invalid_value_uses_default(mock_config):
    """get_int coerces valid ints; garbage falls back to DEFAULT_CONFIG."""
    mock_config._config["DEFAULT_IMAGES_PER_TERM"] = "not-a-number"
    assert mock_config.get_int("DEFAULT_IMAGES_PER_TERM") == ConfigManager.DEFAULT_CONFIG["DEFAULT_IMAGES_PER_TERM"]
    mock_config._config["DEFAULT_IMAGES_PER_TERM"] = 12
    assert mock_config.get_int("DEFAULT_IMAGES_PER_TERM") == 12
