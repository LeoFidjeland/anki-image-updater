import json
import os
import tempfile
import threading
from pathlib import Path
from platformdirs import user_config_dir

APP_NAME = "anki-image-updater"
AUTHOR = "LeoFidjeland"

# Serializes save() across threads/sessions so two concurrent settings saves
# can never interleave and truncate the JSON file. Cheap to hold; saves are
# rare (user clicks the Save button) and short (one small write).
_SAVE_LOCK = threading.Lock()


class ConfigManager:
    """User settings; all built-in defaults live in DEFAULT_CONFIG only."""

    DEFAULT_CONFIG = {
        "PEXELS_API_KEY": "",
        "UNSPLASH_ACCESS_KEY": "",
        "FREEPIK_API_KEY": "",
        "PIXABAY_API_KEY": "",
        "DEFAULT_FIELD_SEARCH": "English",
        "DEFAULT_FIELD_IMAGE": "Image",
        "DEFAULT_FIELD_SOURCE": "Image Source",
        "DEFAULT_IMAGES_PER_TERM": 12,
        "DEFAULT_TAG": "Replaced",
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
        self._backfill_defaults()

    def _backfill_defaults(self):
        """Ensure every key in DEFAULT_CONFIG exists (e.g. after a partial or older file)."""
        for key, value in self.DEFAULT_CONFIG.items():
            if key not in self._config:
                self._config[key] = value

    def save(self):
        """
        Save current configuration to the user config file atomically.

        Writes to a sibling temp file in the same directory and renames it
        over the target — ``os.replace`` is atomic on POSIX and (since Python
        3.3) on Windows, so a concurrent save from another session can
        never leave a half-written JSON file behind. The module-level lock
        serializes Python-side writers for extra safety.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with _SAVE_LOCK:
            tmp_fd = None
            tmp_path = None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(
                    prefix=".settings.",
                    suffix=".json.tmp",
                    dir=str(self.config_dir),
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    tmp_fd = None  # fdopen took ownership
                    json.dump(self._config, f, indent=4)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        # fsync can fail on some filesystems (e.g. certain
                        # network shares). Not fatal — os.replace is still atomic.
                        pass
                os.replace(tmp_path, self.config_file)
                tmp_path = None
            except OSError as e:
                print(f"Error saving config: {e}")
            finally:
                if tmp_fd is not None:
                    try:
                        os.close(tmp_fd)
                    except OSError:
                        pass
                if tmp_path is not None and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    def get(self, key, default=None):
        """Return a setting: env override, then saved value, then DEFAULT_CONFIG, then default."""
        env_val = os.getenv(key)
        if env_val is not None:
            return env_val

        if key in self._config:
            return self._config[key]
        if key in self.DEFAULT_CONFIG:
            return self.DEFAULT_CONFIG[key]
        return default

    def get_int(self, key: str) -> int:
        """Parse integer setting; invalid values fall back to DEFAULT_CONFIG[key]."""
        fallback = int(self.DEFAULT_CONFIG[key])
        raw = self.get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback

    def set(self, key, value):
        """Sets a configuration value and saves it."""
        self._config[key] = value
        self.save()

    @property
    def config_path(self):
        return str(self.config_file)
