"""Cross-platform locations for PostBaby's writable data and bundled resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PostBaby"


def app_data_dir() -> Path:
    """Return a user-writable data directory, creating it on demand."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        directory = Path(root) / APP_NAME if root else Path.home() / "AppData" / "Local" / APP_NAME
    else:
        directory = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def default_database_path() -> Path:
    """Use per-user storage; retain a legacy working-directory DB when present."""
    target = app_data_dir() / "postbaby.db"
    legacy = Path.cwd() / "postbaby.db"
    return legacy if not target.exists() and legacy.is_file() else target


def resource_path(*parts: str) -> Path:
    """Find files from source checkout or PyInstaller's bundled extraction path."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)
