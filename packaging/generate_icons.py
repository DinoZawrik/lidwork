"""Generate release icon assets from the in-app Pillow icon."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
_ICONSET_FILENAMES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="assets",
        help="Directory where lidwork.ico and lidwork.icns should be written.",
    )
    parser.add_argument(
        "--skip-icns",
        action="store_true",
        help="Skip macOS .icns generation even if iconutil is available.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    icon = _load_source_icon()
    _write_ico(icon, output_dir / "lidwork.ico")
    if not args.skip_icns:
        _write_icns(icon, output_dir / "lidwork.icns")
    return 0


def _load_source_icon():
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from lidwork.icons import build_icon

    return build_icon(True).convert("RGBA")


def _write_ico(icon, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    icon.save(output_path, format="ICO", sizes=_ICO_SIZES)


def _write_icns(icon, output_path: Path) -> None:
    iconutil = _find_iconutil()
    if iconutil is None:
        raise RuntimeError("iconutil is required to generate .icns files.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        iconset_dir = Path(temp_dir) / "lidwork.iconset"
        iconset_dir.mkdir()
        for filename, size in _ICONSET_FILENAMES.items():
            resized = icon.resize((size, size), resample=_resampling_filter(icon))
            resized.save(iconset_dir / filename, format="PNG")
        completed = subprocess.run(
            [iconutil, "-c", "icns", str(iconset_dir), "-o", str(output_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode == 0:
        return
    print(
        "iconutil rejected the generated iconset; falling back to Pillow ICNS output.",
        file=sys.stderr,
    )
    icon.save(output_path, format="ICNS")


def _find_iconutil() -> str | None:
    for candidate in ("/usr/bin/iconutil", "iconutil"):
        if Path(candidate).exists():
            return candidate
        location = shutil.which(candidate)
        if location:
            return location
    return None


def _resampling_filter(icon):
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return resampling.LANCZOS


if __name__ == "__main__":
    raise SystemExit(main())
