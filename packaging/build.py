"""Build release artifacts for the current platform."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        default="dist/release",
        help="Directory where release-ready artifacts should be written.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    artifact_dir = (project_root / args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    _generate_icons(project_root)
    _clean_pyinstaller_outputs(project_root)

    if sys.platform == "darwin":
        artifact = _build_macos(project_root, artifact_dir)
    elif sys.platform == "win32":
        artifact = _build_windows(project_root, artifact_dir)
    elif sys.platform.startswith("linux"):
        artifact = _build_linux(project_root, artifact_dir)
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    print(artifact)
    return 0


def _generate_icons(project_root: Path) -> None:
    command = [sys.executable, str(project_root / "packaging" / "generate_icons.py")]
    if sys.platform != "darwin":
        command.append("--skip-icns")
    _run(command, cwd=project_root)


def _clean_pyinstaller_outputs(project_root: Path) -> None:
    for path in (
        project_root / "build",
        project_root / "dist" / "lidwork",
        project_root / "dist" / "lidwork.app",
        project_root / "dist" / "lidwork.exe",
    ):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _build_macos(project_root: Path, artifact_dir: Path) -> Path:
    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "packaging/lidwork-macos.spec"],
        cwd=project_root,
    )
    app_path = project_root / "dist" / "lidwork.app"
    artifact = artifact_dir / f"lidwork-macos-{_normalized_arch()}.zip"
    if artifact.exists():
        artifact.unlink()
    _run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app_path),
            str(artifact),
        ],
        cwd=project_root,
    )
    return artifact


def _build_windows(project_root: Path, artifact_dir: Path) -> Path:
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onefile",
            "--name",
            "lidwork",
            "--icon",
            "assets/lidwork.ico",
            "--collect-submodules",
            "pystray",
            "lidwork/cli.py",
        ],
        cwd=project_root,
    )
    built_path = project_root / "dist" / "lidwork.exe"
    artifact = artifact_dir / f"lidwork-windows-{_normalized_arch()}.exe"
    shutil.copy2(built_path, artifact)
    return artifact


def _build_linux(project_root: Path, artifact_dir: Path) -> Path:
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "lidwork",
            "--collect-submodules",
            "pystray",
            "lidwork/cli.py",
        ],
        cwd=project_root,
    )
    built_path = project_root / "dist" / "lidwork"
    artifact = artifact_dir / f"lidwork-linux-{_normalized_arch()}.tar.gz"
    with tarfile.open(artifact, "w:gz") as handle:
        handle.add(built_path, arcname="lidwork")
    return artifact


def _normalized_arch() -> str:
    raw = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "x64": "x86_64",
        "x86_64": "x86_64",
    }
    return aliases.get(raw, raw)


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
