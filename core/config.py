"""Loads config.toml once; every module reads parameters from here instead of hardcoding them."""
import os
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("DAMAGE_CONFIG", ROOT / "config.toml"))


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def get(section: str, key: str):
    return load_config()[section][key]


def path(key: str) -> Path:
    """Path from the [paths] section, resolved against the repository root."""
    return ROOT / get("paths", key)
