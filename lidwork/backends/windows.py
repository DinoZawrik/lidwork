"""Windows backend."""

from __future__ import annotations

import getpass
import os
import re
import shutil
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
_GUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")


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
            [_system32("schtasks.exe"), "/query", "/tn", _TASK_NAME],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode != 0

    def setup(self) -> None:
        if getattr(sys, "frozen", False):
            _run_elevated(
                str(Path(sys.executable)),
                "--_install-helper",
                "Scheduled task setup failed.",
            )
            return

        task_xml = _build_task_xml()
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-16", suffix=".xml", delete=False
        ) as handle:
            handle.write(task_xml)
            xml_path = Path(handle.name)
        try:
            _create_task_elevated(xml_path)
        finally:
            xml_path.unlink(missing_ok=True)

    def caveats(self) -> list[str]:
        return []

    def _run_apply_task(self) -> None:
        if self.needs_setup():
            raise BackendError("Windows setup is missing. Run lidwork --setup first.")
        try:
            subprocess.run(
                [_system32("schtasks.exe"), "/run", "/tn", _TASK_NAME],
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
        if _GUID_RE.fullmatch(state.win_scheme_guid) is None:
            raise BackendError("Untrusted power scheme GUID.")
        _apply_lid_action(state.win_scheme_guid, 0, 0)
        _activate_scheme(state.win_scheme_guid)
        return 0

    if state.win_scheme_guid is None:
        return 0
    if _GUID_RE.fullmatch(state.win_scheme_guid) is None:
        raise BackendError("Untrusted power scheme GUID.")
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
    if getattr(sys, "frozen", False):
        return str(_program_files_helper_path()), "--_apply-helper"
    return str(Path(sys.executable)), "-m lidwork.cli --_apply-helper"


def _system32(exe: str) -> str:
    """Return an absolute path under System32.

    Args:
        exe: Executable name or relative path under ``System32``.

    Returns:
        The absolute path rooted at the current Windows system directory.
    """
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(root) / "System32" / exe)


def _program_files_helper_path() -> Path:
    """Return the immutable helper location used by frozen builds.

    Returns:
        The Program Files destination for the copied frozen executable.
    """
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return root / "lidwork" / "lidwork.exe"


def _task_user_id() -> str:
    completed = subprocess.run(
        [_system32("whoami.exe")],
        check=False,
        capture_output=True,
        text=True,
    )
    user = completed.stdout.strip()
    return user or getpass.getuser()


def _get_active_scheme_guid() -> str:
    output = _run_command([_system32("powercfg.exe"), "/getactivescheme"])
    match = _SCHEME_GUID_RE.search(output)
    if match is None:
        raise BackendError("Could not parse active power scheme GUID.")
    scheme_guid = match.group(1)
    if _GUID_RE.fullmatch(scheme_guid) is None:
        raise BackendError("Could not parse active power scheme GUID.")
    return scheme_guid


def _query_lid_action_values(scheme: str) -> dict[str, int]:
    output = _run_command(
        [
            _system32("powercfg.exe"),
            "/query",
            scheme,
            _LID_ACTION_GROUP,
            _LID_ACTION_SETTING,
        ]
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
            _system32("powercfg.exe"),
            "/setacvalueindex",
            scheme_guid,
            _LID_ACTION_GROUP,
            _LID_ACTION_SETTING,
            str(ac_value),
        ]
    )
    _run_command(
        [
            _system32("powercfg.exe"),
            "/setdcvalueindex",
            scheme_guid,
            _LID_ACTION_GROUP,
            _LID_ACTION_SETTING,
            str(dc_value),
        ]
    )


def _activate_scheme(scheme_guid: str) -> None:
    _run_command([_system32("powercfg.exe"), "/S", scheme_guid])


def _validate_restore_value(value: int) -> None:
    if value not in {0, 1, 2, 3}:
        raise BackendError(f"Refusing to apply unexpected LIDACTION value: {value}")


def _create_task_elevated(xml_path: Path) -> None:
    """Create the scheduled task via an elevated schtasks invocation.

    Args:
        xml_path: Path to the temporary task XML definition.
    """
    parameters = subprocess.list2cmdline(
        ["/create", "/tn", _TASK_NAME, "/xml", str(xml_path), "/f"]
    )
    _run_elevated(
        _system32("schtasks.exe"),
        parameters,
        "Scheduled task setup failed.",
    )


def _install_frozen_helper() -> int:
    """Install the frozen helper into Program Files and register the task.

    Returns:
        Process exit code.
    """
    source = Path(sys.executable)
    destination = _program_files_helper_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve(strict=False) != destination.resolve(strict=False):
        shutil.copy2(source, destination)

    task_xml = _build_task_xml()
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-16", suffix=".xml", delete=False
    ) as handle:
        handle.write(task_xml)
        xml_path = Path(handle.name)
    try:
        subprocess.run(
            [
                _system32("schtasks.exe"),
                "/create",
                "/tn",
                _TASK_NAME,
                "/xml",
                str(xml_path),
                "/f",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BackendError(
            exc.stderr.strip()
            or exc.stdout.strip()
            or "Scheduled task setup failed."
        ) from exc
    finally:
        xml_path.unlink(missing_ok=True)
    return 0


def _run_elevated(executable: str, parameters: str, failure_message: str) -> None:
    """Run a process with UAC elevation and wait for its exit status.

    Args:
        executable: Absolute executable path to launch with ``runas``.
        parameters: Command-line parameters passed to the elevated process.
        failure_message: Error message used when elevation or execution fails.
    """
    if sys.platform != "win32":
        raise BackendError(failure_message)

    import ctypes
    from ctypes import wintypes

    see_mask_nocloseprocess = 0x00000040
    infinite = 0xFFFFFFFF
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell_execute_ex = shell32.ShellExecuteExW
    shell_execute_ex.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell_execute_ex.restype = wintypes.BOOL

    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD

    get_exit_code_process = kernel32.GetExitCodeProcess
    get_exit_code_process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_exit_code_process.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    execute_info = SHELLEXECUTEINFOW()
    execute_info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    execute_info.fMask = see_mask_nocloseprocess
    execute_info.lpVerb = "runas"
    execute_info.lpFile = executable
    execute_info.lpParameters = parameters
    execute_info.nShow = 0

    if not shell_execute_ex(ctypes.byref(execute_info)):
        raise BackendError(failure_message)

    process_handle = execute_info.hProcess
    if not process_handle:
        raise BackendError(failure_message)

    try:
        wait_for_single_object(process_handle, infinite)
        exit_code = wintypes.DWORD()
        if not get_exit_code_process(process_handle, ctypes.byref(exit_code)):
            raise BackendError(failure_message)
        if exit_code.value != 0:
            raise BackendError(f"{failure_message} Exit code: {exit_code.value}.")
    finally:
        close_handle(process_handle)


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise BackendError(
            exc.stderr.strip() or exc.stdout.strip() or "Command failed."
        ) from exc
    return completed.stdout
