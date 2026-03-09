import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DB_PATH = os.path.join(DATA_DIR, "activity.db")

DEFAULTS = {
    "poll_interval": 10,       # seconds
    "idle_threshold": 300,     # seconds (5 min)
    "api_port": 27420,
    "db_path": DB_PATH,
    "export_dir": "D:/02 Area/Personal Base/Life/Activity",
}


def load() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save(DEFAULTS)
        return dict(DEFAULTS)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # fill missing keys with defaults
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save(cfg: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
