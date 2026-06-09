"""Backend selection."""

from __future__ import annotations

import sys

from lidwork.backends.base import Backend, BackendError


def get_backend() -> Backend:
    """Create the backend for the current platform."""
    if sys.platform == "darwin":
        from lidwork.backends.macos import MacOSBackend

        return MacOSBackend()
    if sys.platform.startswith("linux"):
        from lidwork.backends.linux import LinuxBackend

        return LinuxBackend()
    if sys.platform == "win32":
        from lidwork.backends.windows import WindowsBackend

        return WindowsBackend()
    raise BackendError(f"Unsupported platform: {sys.platform}")


__all__ = ["Backend", "BackendError", "get_backend"]

