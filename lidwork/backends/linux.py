"""Linux backend."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from pathlib import Path

from lidwork.backends.base import Backend, BackendError
from lidwork.state import load_state, save_state


class LinuxBackend(Backend):
    """Backend implementation for Linux."""

    def is_active(self) -> bool:
        pid = load_state().linux_pid
        return pid is not None and _is_lidwork_inhibitor(pid)

    def enable(self) -> None:
        if self.is_active():
            return
        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if _should_detach_inhibitor():
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["preexec_fn"] = _set_parent_death_signal
        try:
            process = subprocess.Popen(
                [
                    "systemd-inhibit",
                    "--what=handle-lid-switch",
                    "--who=lidwork",
                    '--why=keep running with lid closed',
                    "--mode=block",
                    "sleep",
                    "infinity",
                ],
                **popen_kwargs,
            )
        except OSError as exc:
            raise BackendError(f"Could not start systemd-inhibit: {exc}") from exc

        state = load_state()
        state.linux_pid = process.pid
        state.desired = "on"
        save_state(state)

        if not _is_lidwork_inhibitor(process.pid):
            raise BackendError("systemd-inhibit did not stay running.")

    def disable(self) -> None:
        state = load_state()
        pid = state.linux_pid
        if pid is None:
            state.desired = "off"
            save_state(state)
            return
        if _is_lidwork_inhibitor(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                raise BackendError(f"Could not stop systemd-inhibit: {exc}") from exc
        state.desired = "off"
        state.linux_pid = None
        save_state(state)

    def needs_setup(self) -> bool:
        return False

    def setup(self) -> None:
        return None

    def caveats(self) -> list[str]:
        warnings: list[str] = []
        if _desktop_power_manager_detected():
            warnings.append(
                "GNOME/KDE power management may override lid behavior. Also set lid-close to 'Do nothing' in system settings."
            )
        return warnings


def _desktop_power_manager_detected() -> bool:
    completed = subprocess.run(
        ["ps", "-ax", "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    haystack = completed.stdout.lower()
    needles = (
        "gnome-settings-daemon",
        "org.gnome.settingsdaemon.power",
        "gsd-power",
        "powerdevil",
    )
    return any(needle in haystack for needle in needles)


def _is_lidwork_inhibitor(pid: int) -> bool:
    command_line = _command_line_for_pid(pid)
    return command_line is not None and "systemd-inhibit" in command_line and "--who=lidwork" in command_line


def _command_line_for_pid(pid: int) -> str | None:
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    if proc_cmdline.exists():
        try:
            raw = proc_cmdline.read_bytes()
        except OSError:
            return None
        text = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
        return text or None

    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    return text or None


def _should_detach_inhibitor() -> bool:
    return "--on" in sys.argv[1:]


def _set_parent_death_signal() -> None:
    libc = ctypes.CDLL(None)
    pr_set_pdeathsig = 1
    libc.prctl(pr_set_pdeathsig, signal.SIGTERM)
