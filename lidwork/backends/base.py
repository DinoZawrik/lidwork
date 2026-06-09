"""Backend interface for per-platform lid behavior control."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BackendError(RuntimeError):
    """Raised when a backend action cannot be completed."""


class Backend(ABC):
    """Abstract interface for platform-specific lid handling.

    Implementations must read real operating-system state rather than trusting a
    cached in-memory flag.
    """

    @abstractmethod
    def is_active(self) -> bool:
        """Return whether keep-awake mode is currently active.

        Returns:
            bool: True when the underlying OS setting or inhibitor is active.
        """

    @abstractmethod
    def enable(self) -> None:
        """Enable keep-awake mode.

        Implementations that mutate OS settings must snapshot the original state
        before making changes.
        """

    @abstractmethod
    def disable(self) -> None:
        """Disable keep-awake mode and restore the original state."""

    @abstractmethod
    def needs_setup(self) -> bool:
        """Return whether one-time privileged setup is still required.

        Returns:
            bool: True when setup has not yet been completed.
        """

    @abstractmethod
    def setup(self) -> None:
        """Perform one-time privileged setup for the backend."""

    @abstractmethod
    def caveats(self) -> list[str]:
        """Return warnings or caveats that should be surfaced to the user.

        Returns:
            list[str]: Human-readable caveats for the active platform.
        """

