import json
import os
from pathlib import Path
from platformdirs import user_config_dir

APP_NAME = "anki-image-updater"
AUTHOR = "LeoFidjeland"

class ConfigManager:
    DEFAULT_CONFIG = {
        "PEXELS_API_KEY": "",
        "UNSPLASH_ACCESS_KEY": "",
        "FREEPIK_API_KEY": "",
        "DEFAULT_FIELD_SEARCH": "English",
        "DEFAULT_FIELD_IMAGE": "Image",
        "DEFAULT_FIELD_SOURCE": "Image Source",
        "DEFAULT_IMAGES_PER_TERM": 6,
        "DEFAULT_TAG": "replaced"
    }

    def __init__(self):
        self.config_dir = Path(user_config_dir(APP_NAME, AUTHOR))
        self.config_file = self.config_dir / "settings.json"
        self._config = self.DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        """Loads configuration from the user config file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    # Update defaults with saved values
                    self._config.update(saved_config)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error loading config: {e}")

    def save(self):
        """Saves current configuration to the user config file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4)
        except OSError as e:
            print(f"Error saving config: {e}")

    def get(self, key, default=None):
        """Gets a configuration value, prioritizing env vars then config file."""
        # Environment variable override (useful for dev/testing)
        env_val = os.getenv(key)
        if env_val is not None:
            return env_val
        
        return self._config.get(key, default)

    def set(self, key, value):
        """Sets a configuration value and saves it."""
        self._config[key] = value
        self.save()

    @property
    def config_path(self):
        return str(self.config_file)
