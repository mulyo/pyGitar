"""Resolusi path untuk cache, database, dan data aplikasi."""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["app_data_dir", "cache_dir", "db_path", "ensure_dirs"]

_APP_NAME = "GuitarLoop"


def app_data_dir() -> Path:
    """Folder data per pengguna (database, pengaturan)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / _APP_NAME
        return Path.home() / "AppData" / "Roaming" / _APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / _APP_NAME.lower()
    return Path.home() / ".local" / "share" / _APP_NAME.lower()


def cache_dir() -> Path:
    """Folder cache (WAV import, peaks numpy)."""
    if sys.platform.startswith("win"):
        return app_data_dir() / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP_NAME
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / _APP_NAME.lower()
    return Path.home() / ".cache" / _APP_NAME.lower()


def db_path() -> Path:
    return app_data_dir() / "guitarloop.db"


def ensure_dirs() -> None:
    """Pastikan folder data & cache sudah ada; buat jika belum."""
    app_data_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)
