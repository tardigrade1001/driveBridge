"""
DriveBridge Configuration
Edit values here or through the Settings GUI.
"""
import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "drivebridge_config.json"

DEFAULT_CONFIG = {
    # Paths to rclone executable
    "rclone_path": r"C:\Program Files\rclone\rclone.exe",

    # rclone remote name (from rclone config)
    "remote_name": "gdrive",

    # Drive folder to sync with (name, e.g. "Projects" or "Posters")
    "drive_folder": "Posters",

    # Local folder for bisync
    "local_folder": "",

    # Sync behaviour
    "sync_mode": "interval",
    "sync_interval_minutes": 30,
    "confirm_deletions": True,
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get(key):
    return load_config().get(key)


def set_value(key, value):
    config = load_config()
    config[key] = value
    save_config(config)
