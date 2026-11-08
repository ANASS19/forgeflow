"""Resolve local storage without creating directories during read-only commands."""

import os
import sys
from pathlib import Path


def data_directory(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    if configured := os.environ.get("FORGEFLOW_DATA_DIR"):
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ForgeFlow"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ForgeFlow"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "forgeflow"
