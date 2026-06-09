"""macOS backend."""

from __future__ import annotations

import getpass
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from lidwork.backends.base import Backend, BackendError


class MacOSBackend(Backend):
    """Backend implementation for macOS."""

    _SUDOERS_PATH = Path("/etc/sudoers.d/lidwork")

    def is_active(self) -> bool:
        output = _run_command(["/usr/bin/pmset", "-g"])
        for line in output.splitlines():
            lower = line.lower()
            if "sleepdisabled" in lower:
                parts = line.split()
                return bool(parts and parts[-1] == "1")
        raise BackendError("Could not determine SleepDisabled from pmset output.")

    def enable(self) -> None:
        if self.is_active():
            return
        self._set_active(True)

    def disable(self) -> None:
        if not self.is_active():
            return
        self._set_active(False)

    def needs_setup(self) -> bool:
        expected = self._sudoers_content()
        if os.access(self._SUDOERS_PATH, os.R_OK):
            try:
                return self._SUDOERS_PATH.read_text(encoding="utf-8") != expected
            except OSError:
                pass
        return not (_can_run_passwordless_pmset("0") and _can_run_passwordless_pmset("1"))

    def setup(self) -> None:
        content = self._sudoers_content()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        command = " && ".join(
            [
                "/usr/bin/install -d -o root -g wheel -m 0755 /etc/sudoers.d",
                f"/usr/sbin/visudo -cf {shlex.quote(str(temp_path))}",
                (
                    "/usr/bin/install -o root -g wheel -m 0440 "
                    f"{shlex.quote(str(temp_path))} {shlex.quote(str(self._SUDOERS_PATH))}"
                ),
            ]
        )
        try:
            subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    f"do shell script {_applescript_quote(command)} with administrator privileges",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(exc.stderr.strip() or exc.stdout.strip() or "Setup failed.") from exc
        finally:
            temp_path.unlink(missing_ok=True)

    def caveats(self) -> list[str]:
        return ["macOS uses pmset disablesleep: this disables all sleep, not only lid sleep."]

    def _set_active(self, active: bool) -> None:
        value = "1" if active else "0"
        try:
            subprocess.run(
                ["/usr/bin/sudo", "-n", "/usr/bin/pmset", "-a", "disablesleep", value],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip()
            if exc.returncode != 0 and self.needs_setup():
                message = message or "Passwordless pmset access is not configured. Run lidwork --setup."
            raise BackendError(message or "pmset command failed.") from exc

    @staticmethod
    def _sudoers_content() -> str:
        user = getpass.getuser()
        return (
            f"{user} ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, "
            "/usr/bin/pmset -a disablesleep 1\n"
        )


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise BackendError(exc.stderr.strip() or exc.stdout.strip() or "Command failed.") from exc
    return completed.stdout


def _can_run_passwordless_pmset(value: str) -> bool:
    try:
        completed = subprocess.run(
            ["/usr/bin/sudo", "-n", "-l", "/usr/bin/pmset", "-a", "disablesleep", value],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _applescript_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
