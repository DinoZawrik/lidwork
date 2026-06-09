"""macOS backend."""

from __future__ import annotations

import os
import pwd
import re
import shlex
import subprocess
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
        content = shlex.quote(self._sudoers_content().rstrip("\n"))
        command = "\n".join(
            [
                "set -e",
                "umask 077",
                'tmp=$(/usr/bin/mktemp)',
                'trap \'/bin/rm -f "$tmp"\' EXIT',
                f"printf '%s\\n' {content} > \"$tmp\"",
                '/usr/sbin/visudo -cf "$tmp"',
                "/usr/bin/install -d -o root -g wheel -m 0755 /etc/sudoers.d",
                (
                    "/usr/bin/install -o root -g wheel -m 0440 "
                    f"\"$tmp\" {shlex.quote(str(self._SUDOERS_PATH))}"
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
        user = pwd.getpwuid(os.getuid()).pw_name
        if re.fullmatch(r"[A-Za-z0-9._-]+", user) is None:
            raise BackendError("Resolved macOS username is not safe for sudoers.")
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
