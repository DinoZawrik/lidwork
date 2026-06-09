# lidwork

`lidwork` is a small cross-platform tray utility that toggles "keep running with
the lid closed" behavior on macOS, Linux, and Windows from one Python codebase.

## Download

Prebuilt releases live at: <https://github.com/DinoZawrik/lidwork/releases>

- macOS (Apple Silicon):
  Download the `lidwork-macos-arm64.zip` archive, unzip it, then move
  `lidwork.app` to `/Applications` or another stable folder before first launch.
  Intel Macs are not prebuilt — run from source (see Install below).
- Windows:
  Download `lidwork-windows-*.exe`, place it in a stable folder first, then run
  it from there. If you later move the exe, run `lidwork.exe --setup` again
  because the scheduled task stores an absolute path.
- Linux:
  Download the `lidwork-linux-*.tar.gz` archive, extract it, then run the
  `lidwork` binary from the extracted folder.

The binaries are unsigned:

- macOS:
  On first launch, use `right-click -> Open`, or remove quarantine manually:

  ```bash
  xattr -dr com.apple.quarantine /path/to/lidwork.app
  ```

- Windows:
  If SmartScreen appears, use `More info -> Run anyway`.

Because they are unsigned, verify integrity/authenticity first — each release
ships a `SHA256SUMS` file and signed build provenance:

```bash
shasum -a 256 -c SHA256SUMS                       # checksum
gh attestation verify <file> --repo DinoZawrik/lidwork  # provenance
```

See [SECURITY.md](SECURITY.md) for the threat model and privilege design.

## Install

```bash
pip install -e .
```

Run the tray app:

```bash
lidwork
```

Run headless commands:

```bash
lidwork --status
lidwork --on
lidwork --off
lidwork --setup
```

## Platform behavior

### macOS

- Mechanism: `pmset -a disablesleep 0|1`
- Honesty caveat: `disablesleep 1` disables all sleep, not only lid-close sleep.
  The tray/menu wording is "Keep awake (lid closed OK)" for that reason.
- One-time setup installs `/etc/sudoers.d/lidwork` so `--on` and `--off` can run
  `pmset` without prompting every time.
- For launch at login, add `lidwork.app` to `System Settings -> General ->
  Login Items`.

Setup:

```bash
lidwork --setup
```

If the app or shell dies while ON, the setting is still visible and recoverable:

```bash
sudo pmset -a disablesleep 0
```

### Linux

- Mechanism: `systemd-inhibit --what=handle-lid-switch ... sleep infinity`
- No root setup is required.
- `lidwork --on` starts the inhibitor; `lidwork --off` terminates it.
- Limitation: this only blocks `systemd-logind`. GNOME/KDE power management may
  still override lid-close behavior. If `lidwork` detects a GNOME/KDE power
  daemon, it warns in the tray/menu and status output. You may also need to set
  lid-close to "Do nothing" in desktop power settings.
- Best effort only: the release binary expects a tray-capable desktop
  environment plus AppIndicator/GTK runtime libraries such as
  `libayatana-appindicator`. Releases are built on Ubuntu 22.04, so older glibc
  versions may not be compatible.

### Windows

- Mechanism: `powercfg` changes the active power scheme's `LIDACTION` to
  "Do nothing" (`0`) for both AC and DC.
- One-time setup creates the `lidwork_apply` scheduled task with
  `RunLevel=Highest`.
- `--on` snapshots the active scheme GUID plus the original AC/DC `LIDACTION`
  values into the state file, then asks the elevated helper to apply `0`.
- `--off` restores the exact snapshotted values and re-activates that scheme.
- If the machine restarts while ON, the saved snapshot remains in the state file
  so `lidwork --off` can still restore it.
- Put `lidwork.exe` in its long-term folder before running `lidwork --setup`.
  If the exe moves later, re-run `lidwork --setup` so the scheduled task points
  at the new path.
- For launch at login without Task Scheduler changes, place a shortcut to
  `lidwork.exe` in the user's Startup folder.

If you get stuck ON, you can also restore the lid-close setting manually from
Windows power settings.

## Uninstall

1. Turn the feature OFF before uninstalling:

   ```bash
   lidwork --off
   ```

2. Remove the platform-specific privileged setup if it was installed:

- macOS:

  ```bash
  sudo rm -f /etc/sudoers.d/lidwork
  ```

- Windows:

  ```powershell
  schtasks /delete /tn lidwork_apply /f
  ```

3. Remove the package:

   ```bash
   pip uninstall lidwork
   ```

4. Optionally remove the user config directory:

- macOS: `~/Library/Application Support/lidwork`
- Linux: `~/.config/lidwork` or `$XDG_CONFIG_HOME/lidwork`
- Windows: `%LOCALAPPDATA%\lidwork`

## Notes

- The tray implementation uses `pystray` + `Pillow`, as specified.
- `pystray` is known to be weaker on Linux than on macOS/Windows. If Linux tray
  behavior proves flaky in real-world testing, the intended fallback is
  `PySide6`/`QSystemTrayIcon`, but that is not part of v1.
- Release builds are created with PyInstaller. Source installs only need
  `pystray` and `Pillow`; `pyinstaller` is build-time only.
