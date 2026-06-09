"""Windows backend."""

from __future__ import annotations

import getpass
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from xml.sax.saxutils import escape

from lidwork.backends.base import Backend, BackendError
from lidwork.state import load_state, save_state


_TASK_NAME = "lidwork_apply"
_LID_ACTION_GROUP = "SUB_BUTTONS"
_LID_ACTION_SETTING = "LIDACTION"
_LID_ACTION_HEX_RE = re.compile(
    r"Current (AC|DC) Power Setting Index:\s+(0x[0-9a-fA-F]+)"
)
_SCHEME_GUID_RE = re.compile(r"Power Scheme GUID:\s+([0-9A-Fa-f-]+)")


class WindowsBackend(Backend):
    """Backend implementation for Windows."""

    def is_active(self) -> bool:
        values = _query_lid_action_values("SCHEME_CURRENT")
        return values["ac"] == 0

    def enable(self) -> None:
        if self.is_active():
            return
        scheme_guid = _get_active_scheme_guid()
        values = _query_lid_action_values("SCHEME_CURRENT")
        state = load_state()
        state.desired = "on"
        state.win_scheme_guid = scheme_guid
        state.win_restore_ac = values["ac"]
        state.win_restore_dc = values["dc"]
        save_state(state)
        self._run_apply_task()

    def disable(self) -> None:
        state = load_state()
        state.desired = "off"
        save_state(state)
        if state.win_scheme_guid is None:
            return
        self._run_apply_task()

    def needs_setup(self) -> bool:
        completed = subprocess.run(
            ["schtasks", "/query", "/tn", _TASK_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode != 0

    def setup(self) -> None:
        task_xml = _build_task_xml()
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-16", suffix=".xml", delete=False
        ) as handle:
            handle.write(task_xml)
            xml_path = Path(handle.name)
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$process = Start-Process schtasks -Verb RunAs -Wait -PassThru "
                f"-ArgumentList '/create','/tn','{_TASK_NAME}','/xml','{xml_path}','/f'; "
                "exit $process.ExitCode"
            ),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                exc.stderr.strip()
                or exc.stdout.strip()
                or "Scheduled task setup failed."
            ) from exc
        finally:
            xml_path.unlink(missing_ok=True)

    def caveats(self) -> list[str]:
        return []

    def _run_apply_task(self) -> None:
        if self.needs_setup():
            raise BackendError("Windows setup is missing. Run lidwork --setup first.")
        try:
            subprocess.run(
                ["schtasks", "/run", "/tn", _TASK_NAME],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                exc.stderr.strip()
                or exc.stdout.strip()
                or "Could not run lidwork_apply."
            ) from exc


def run_apply_helper() -> int:
    """Run the elevated helper invoked by the scheduled task."""
    state = load_state()
    desired = state.desired
    if desired == "on":
        if state.win_scheme_guid is None:
            raise BackendError("Missing snapshotted power scheme GUID.")
        _apply_lid_action(state.win_scheme_guid, 0, 0)
        _activate_scheme(state.win_scheme_guid)
        return 0

    if state.win_scheme_guid is None:
        return 0
    if state.win_restore_ac is None or state.win_restore_dc is None:
        raise BackendError("Missing snapshotted restore values.")
    _validate_restore_value(state.win_restore_ac)
    _validate_restore_value(state.win_restore_dc)
    _apply_lid_action(state.win_scheme_guid, state.win_restore_ac, state.win_restore_dc)
    _activate_scheme(state.win_scheme_guid)
    return 0


def _build_task_xml() -> str:
    command, arguments = _task_command_and_arguments()
    user_id = escape(_task_user_id())
    return dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>Apply lidwork power settings.</Description>
          </RegistrationInfo>
          <Principals>
            <Principal id="Author">
              <UserId>{user_id}</UserId>
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>HighestAvailable</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <AllowStartOnDemand>true</AllowStartOnDemand>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
            <Hidden>true</Hidden>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <StartWhenAvailable>true</StartWhenAvailable>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{escape(command)}</Command>
              <Arguments>{escape(arguments)}</Arguments>
            </Exec>
          </Actions>
        </Task>
        """
    )


def _task_command_and_arguments() -> tuple[str, str]:
    executable = str(Path(sys.executable))
    if getattr(sys, "frozen", False):
        return executable, "--_apply-helper"
    return executable, "-m lidwork.cli --_apply-helper"


def _task_user_id() -> str:
    completed = subprocess.run(
        ["whoami"],
        check=False,
        capture_output=True,
        text=True,
    )
    user = completed.stdout.strip()
    return user or getpass.getuser()


def _get_active_scheme_guid() -> str:
    output = _run_command(["powercfg", "/getactivescheme"])
    match = _SCHEME_GUID_RE.search(output)
    if match is None:
        raise BackendError("Could not parse active power scheme GUID.")
    return match.group(1)


def _query_lid_action_values(scheme: str) -> dict[str, int]:
    output = _run_command(
        ["powercfg", "/query", scheme, _LID_ACTION_GROUP, _LID_ACTION_SETTING]
    )
    values: dict[str, int] = {}
    for match in _LID_ACTION_HEX_RE.finditer(output):
        values[match.group(1).lower()] = int(match.group(2), 16)
    if "ac" not in values or "dc" not in values:
        raise BackendError("Could not parse LIDACTION values from powercfg output.")
    return values


def _apply_lid_action(scheme_guid: str, ac_value: int, dc_value: int) -> None:
    _validate_restore_value(ac_value)
    _validate_restore_value(dc_value)
    _run_command(
        [
            "powercfg",
            "/setacvalueindex",
            scheme_guid,
            _LID_ACTION_GROUP,
            _LID_ACTION_SETTING,
            str(ac_value),
        ]
    )
    _run_command(
        [
            "powercfg",
            "/setdcvalueindex",
            scheme_guid,
            _LID_ACTION_GROUP,
            _LID_ACTION_SETTING,
            str(dc_value),
        ]
    )


def _activate_scheme(scheme_guid: str) -> None:
    _run_command(["powercfg", "/S", scheme_guid])


def _validate_restore_value(value: int) -> None:
    if value not in {0, 1, 2, 3}:
        raise BackendError(f"Refusing to apply unexpected LIDACTION value: {value}")


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise BackendError(
            exc.stderr.strip() or exc.stdout.strip() or "Command failed."
        ) from exc
    return completed.stdout
