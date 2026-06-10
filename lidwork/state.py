"""Persistent state helpers for lidwork."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


DesiredState = Literal["on", "off"]


@dataclass(slots=True)
class AppState:
    """Persisted lidwork state."""

    desired: DesiredState = "off"
    win_scheme_guid: str | None = None
    win_restore_ac: int | None = None
    win_restore_dc: int | None = None
    linux_pid: int | None = None


def get_config_dir() -> Path:
    """Return the per-user config directory."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "lidwork"
    if sys.platform.startswith("linux"):
        base = os.environ.get("XDG_CONFIG_HOME")
        return Path(base) / "lidwork" if base else home / ".config" / "lidwork"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "lidwork"
        return home / "AppData" / "Local" / "lidwork"
    return home / ".lidwork"


def get_state_path() -> Path:
    """Return the path to the JSON state file."""
    return get_config_dir() / "state.json"


def ensure_config_dir() -> Path:
    """Create the config directory if needed."""
    path = get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state() -> AppState:
    """Load state from disk.

    Returns:
        AppState: Parsed state, or defaults if the file does not exist or is
        invalid.
    """
    path = get_state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppState()
    except (OSError, json.JSONDecodeError):
        return AppState()

    desired = raw.get("desired", "off")
    if desired not in {"on", "off"}:
        desired = "off"
    return AppState(
        desired=desired,
        win_scheme_guid=_as_optional_str(raw.get("win_scheme_guid")),
        win_restore_ac=_as_optional_int(raw.get("win_restore_ac")),
        win_restore_dc=_as_optional_int(raw.get("win_restore_dc")),
        linux_pid=_as_optional_int(raw.get("linux_pid")),
    )


def save_state(state: AppState) -> None:
    """Atomically write state to disk."""
    config_dir = ensure_config_dir()
    payload = json.dumps(asdict(state), indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=config_dir,
        delete=False,
        prefix="state.",
        suffix=".tmp",
    ) as handle:
        handle.write(payload)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(get_state_path())


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
