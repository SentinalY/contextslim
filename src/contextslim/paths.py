"""Cross-platform filesystem paths.

Nothing in ContextSlim ever hardcodes a path. Every location is either
derived from :mod:`platformdirs` (so it is correct on macOS, Linux and
Windows) or supplied through an environment variable. Runtime directories
are created on demand, so a fresh clone works with zero manual setup.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "contextslim"
APP_AUTHOR = "ContextSlim"


def default_data_home() -> Path:
    """Return the OS-standard per-user data directory for ContextSlim.

    macOS   -> ~/Library/Application Support/contextslim
    Linux   -> ~/.local/share/contextslim  (honours XDG_DATA_HOME)
    Windows -> %LOCALAPPDATA%\\ContextSlim\\contextslim
    """
    return Path(user_data_dir(APP_NAME, APP_AUTHOR))


def expand(path: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and environment variables, then make the path absolute."""
    raw = os.path.expandvars(str(path))
    return Path(raw).expanduser().resolve()


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """Create ``path`` (and parents) if missing and return it."""
    resolved = expand(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_parent_dir(path: str | os.PathLike[str]) -> Path:
    """Create the parent directory of ``path`` if missing and return ``path``."""
    resolved = expand(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
