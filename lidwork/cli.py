"""Command-line entry points for lidwork."""

from __future__ import annotations

import argparse
import sys

from lidwork.backends import BackendError, get_backend


def main() -> int:
    """Run the lidwork CLI.

    Returns:
        int: Process exit code.
    """
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args._apply_helper:
            return _run_apply_helper()
        if args._install_helper:
            return _run_install_helper()
        if args.status:
            return run_status()
        if args.setup:
            return run_setup()
        if args.on:
            return run_toggle(True)
        if args.off:
            return run_toggle(False)
        from lidwork.app import run_tray_app

        run_tray_app()
        return 0
    except BackendError as exc:
        print(f"lidwork: {exc}", file=sys.stderr)
        return 1


def run_status() -> int:
    """Print the current backend status.

    Returns:
        int: Process exit code.
    """
    backend = get_backend()
    status = "ON" if backend.is_active() else "OFF"
    print(status)
    if backend.needs_setup():
        print("Setup required")
    for caveat in backend.caveats():
        print(f"- {caveat}")
    return 0


def run_setup() -> int:
    """Run one-time backend setup.

    Returns:
        int: Process exit code.
    """
    backend = get_backend()
    backend.setup()
    print("Setup complete.")
    return 0


def run_toggle(enable: bool) -> int:
    """Enable or disable keep-awake mode.

    Args:
        enable: True to enable the feature, False to disable it.

    Returns:
        int: Process exit code.
    """
    backend = get_backend()
    if backend.needs_setup():
        raise BackendError("One-time setup is required. Run lidwork --setup first.")
    if enable:
        backend.enable()
    else:
        backend.disable()
    print("ON" if backend.is_active() else "OFF")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lidwork")
    parser.add_argument("--status", action="store_true", help="Print current state and caveats.")
    parser.add_argument("--on", action="store_true", help="Enable keep-awake mode.")
    parser.add_argument("--off", action="store_true", help="Disable keep-awake mode.")
    parser.add_argument("--setup", action="store_true", help="Run one-time privileged setup.")
    parser.add_argument("--_apply-helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_install-helper", action="store_true", help=argparse.SUPPRESS)
    return parser


def _run_apply_helper() -> int:
    if sys.platform != "win32":
        raise BackendError("Windows apply helper can only run on Windows.")
    from lidwork.backends._win_helper import run_apply_helper

    return run_apply_helper()


def _run_install_helper() -> int:
    if sys.platform != "win32":
        raise BackendError("Windows install helper can only run on Windows.")
    from lidwork.backends.windows import _install_frozen_helper

    return _install_frozen_helper()


if __name__ == "__main__":
    raise SystemExit(main())
