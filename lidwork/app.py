"""Tray application wiring."""

from __future__ import annotations

import threading

import pystray
from pystray import MenuItem as Item

from lidwork.backends import BackendError, get_backend
from lidwork.icons import build_icon


class TrayApplication:
    """Small pystray wrapper around the current backend."""

    def __init__(self) -> None:
        self.backend = get_backend()
        self.icon = pystray.Icon("lidwork", build_icon(False), "lidwork")
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._set_icon_state()
        self.icon.menu = self._build_menu()

    def run(self) -> None:
        poll_thread = threading.Thread(target=self._poll_loop, name="lidwork-poll", daemon=True)
        poll_thread.start()
        self.icon.run()

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(5.0):
            self._set_icon_state()

    def _build_menu(self) -> pystray.Menu:
        items: list[Item] = []
        if self._safe_needs_setup():
            items.append(Item("Run one-time setup", self._handle_setup))
        items.append(Item(lambda _item: self._status_label(), None, enabled=False))
        items.append(Item(lambda _item: self._toggle_label(), self._handle_toggle))
        for caveat in self.backend.caveats():
            items.append(Item(caveat, None, enabled=False))
        if self._last_error:
            items.append(Item(f"Error: {self._last_error}", None, enabled=False))
        items.append(Item("Quit", self._handle_quit))
        return pystray.Menu(*items)

    def _handle_setup(self, icon: pystray.Icon, item: Item) -> None:
        del item
        try:
            self.backend.setup()
        except BackendError as exc:
            self._record_error(str(exc))
        else:
            self._record_error(None)
        finally:
            self._refresh(icon)

    def _handle_toggle(self, icon: pystray.Icon, item: Item) -> None:
        del item
        try:
            if self.backend.needs_setup():
                self.backend.setup()
            if self.backend.is_active():
                self.backend.disable()
            else:
                self.backend.enable()
        except BackendError as exc:
            self._record_error(str(exc))
        else:
            self._record_error(None)
        finally:
            self._refresh(icon)

    def _handle_quit(self, icon: pystray.Icon, item: Item) -> None:
        del item
        self._stop_event.set()
        icon.stop()

    def _refresh(self, icon: pystray.Icon) -> None:
        self._set_icon_state()
        icon.menu = self._build_menu()
        icon.update_menu()

    def _set_icon_state(self) -> None:
        with self._lock:
            try:
                active = self.backend.is_active()
                tooltip = self._tooltip(active)
                self.icon.icon = build_icon(active)
                self.icon.title = tooltip
                self.icon.menu = self._build_menu()
                self.icon.update_menu()
            except BackendError as exc:
                self._record_error(str(exc))

    def _record_error(self, message: str | None) -> None:
        self._last_error = message
        if message:
            try:
                self.icon.notify(message, "lidwork")
            except Exception:
                return

    def _status_label(self) -> str:
        try:
            status = "ON" if self.backend.is_active() else "OFF"
        except BackendError as exc:
            self._record_error(str(exc))
            status = "UNKNOWN"
        suffix = " (setup required)" if self._safe_needs_setup() else ""
        return f"Keep awake (lid closed OK): {status}{suffix}"

    def _toggle_label(self) -> str:
        try:
            active = self.backend.is_active()
        except BackendError as exc:
            self._record_error(str(exc))
            return "Retry refresh"
        return "Disable keep awake (lid closed OK)" if active else "Enable keep awake (lid closed OK)"

    def _tooltip(self, active: bool) -> str:
        state = "ON" if active else "OFF"
        caveat = self.backend.caveats()
        if caveat:
            return f"lidwork: {state} | {caveat[0]}"
        return f"lidwork: {state}"

    def _safe_needs_setup(self) -> bool:
        try:
            return self.backend.needs_setup()
        except BackendError as exc:
            self._record_error(str(exc))
            return False


def run_tray_app() -> None:
    """Run the tray application."""
    TrayApplication().run()
