# lidwork — Design Spec

One-click tray/menu-bar toggle that lets a laptop keep running with the **lid
closed** (clamshell), cross-platform: macOS / Linux / Windows. One Python
codebase.

Status: **spec** (authored by Claude/Opus, 2026-06-09). Implementation delegated
to Codex against this document. Reviewed by Codex copilot — findings folded in
(see §8).

---

## 1. Goal & scope

**Goal.** A persistent tray icon. Click → toggle "keep running with lid closed"
ON/OFF. Icon reflects current state. Survives app restart (reads real OS state,
never trusts a cached flag). No per-toggle password/UAC prompt after a one-time
setup.

**In scope:** the toggle, state detection, one-time privilege setup per OS,
crash-safe restore of original settings.

**Out of scope (v1):** auto-off on low battery, scheduling, GUI beyond the tray
menu, packaging into signed installers (ship as `pip install -e .` + launch
script). Note these as future work, don't build them.

**Non-negotiable behaviors:**
- Toggle OFF must restore the machine to its **original** lid behavior, not a
  hardcoded default. Snapshot-before-change on every OS that mutates a setting.
- Reflect the *actual* OS state on launch — if the user changed it elsewhere,
  the icon must match reality.
- Never leave the machine permanently unable to sleep if the app crashes (see
  §6 crash-safety).

---

## 2. Per-OS mechanism (authoritative — do not substitute)

### macOS
- **Mechanism:** `sudo pmset -a disablesleep {0|1}`.
- **Honesty caveat (surface in UI tooltip + README):** `disablesleep 1` disables
  **all** sleep (idle + lid), not only lid-close. That is acceptable and is the
  only reliable way to keep running clamshell on battery. Label the toggle
  "Keep awake (lid closed OK)", not "lid-only".
- **State read:** `pmset -g | grep -i SleepDisabled` → `1` = active.
- **Passwordless:** one-time setup writes `/etc/sudoers.d/lidwork`:
  ```
  <user> ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1
  ```
  - Exactly these two command forms, no globs/regex/wrapper.
  - File must be root-owned, mode `0440`.
  - Validate before install: `visudo -cf <tmpfile>` then move into place; never
    write the live file unvalidated.
  - Setup itself requires one privileged step — run it via an
    `osascript -e 'do shell script ... with administrator privileges'` prompt or
    instruct the user to run a `lidwork --setup` that uses `sudo`.

### Linux
- **Mechanism:** hold a long-lived inhibitor subprocess while ON:
  ```
  systemd-inhibit --what=handle-lid-switch --who=lidwork \
    --why="keep running with lid closed" --mode=block sleep infinity
  ```
  Kill it (SIGTERM) to release. **No root required.**
- Confirmed by Codex review: low-level `handle-lid-switch` makes the
  `logind.conf` `HandleLidSwitch*` policy branches irrelevant while held — you do
  **not** need `*-external-power` / `*-docked` variants. Killing the child is the
  clean release path.
- **Known limitation (must be documented + detected):** this inhibits
  **systemd-logind only**. On desktops where GNOME/KDE power management owns lid
  behavior, the inhibitor alone may not stop suspend. On launch, best-effort
  detect a running DE power manager (e.g. `gnome-settings-daemon`,
  `org.gnome.SettingsDaemon.Power`, KDE `powerdevil`) and, if found, show a
  one-line warning in the menu/tooltip: "GNOME/KDE may override — also set
  lid-close to 'Do nothing' in system settings." Do not try to auto-edit DE
  settings in v1.
- **State read:** the inhibitor subprocess we spawned is alive (track its PID /
  Popen handle). On launch we cannot reliably detect a *previous* run's
  inhibitor, so on a fresh launch state = OFF unless our own process is holding
  it. Acceptable for v1; document it.

### Windows
- **Mechanism:** set the active power scheme's lid-close action to "Do nothing":
  ```
  powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
  powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
  powercfg /S SCHEME_CURRENT
  ```
  (`0` = Do nothing; AC = plugged, DC = battery.)
- **Snapshot/restore (required — Codex flagged this):** before setting `0`, read
  the current AC and DC `LIDACTION` for the active scheme via
  `powercfg /query SCHEME_CURRENT SUB_BUTTONS LIDACTION` and persist them
  (§5 state file). Toggle OFF restores those exact values, not a hardcoded `1`.
  If the user switched power plans while ON, restore must target the scheme that
  was snapshotted (store the scheme GUID too).
- **Privilege (avoid per-toggle UAC):** create **one** scheduled task at setup,
  `RunLevel=Highest`, that runs a small elevated helper. The helper reads the
  **desired action + restore values from the state file** (§5) and applies them —
  no runtime args passed to the task (Task Scheduler `/run` can't pass args
  reliably). Tray app (non-elevated) writes intent to the state file, then
  `schtasks /run /tn lidwork_apply`. The helper must validate it only ever sets
  `LIDACTION` to `0` or to the snapshotted restore value — nothing else.
  - Setup (`schtasks /create`) needs admin once → triggers UAC once.
  - Querying state (`powercfg /query`) needs no admin → tray app can read state
    directly.
- **State read:** parse `powercfg /query SCHEME_CURRENT SUB_BUTTONS LIDACTION`;
  current AC index `0` = active (for our purposes ON = lid action is Do-nothing).

---

## 3. Architecture

Single Python package, tray via **`pystray` + `Pillow`** (minimal deps, true one
codebase). Codex review note: pystray is stale (0.19.5, 2023) and its weak spot
is the Linux backend; if Linux tray proves flaky during testing, the documented
fallback is `PySide6` `QSystemTrayIcon`. Start with pystray; do **not** pull in
PySide6 unless Linux forces it. Flag in README either way.

```
lidwork/
  lidwork/
    __init__.py
    cli.py            # entry point: default→tray; --on/--off/--status/--setup
    app.py            # pystray Icon, menu, state polling loop, wiring
    icons.py          # Pillow-generated icons: active (filled/green) vs idle (outline/grey)
    state.py          # persisted state (scheme guid, restore values) — JSON in user config dir
    backends/
      __init__.py     # get_backend() -> Backend, by sys.platform
      base.py         # Backend ABC
      macos.py
      linux.py
      windows.py
      _win_helper.py  # elevated helper invoked by scheduled task (Windows only)
  pyproject.toml      # deps: pystray, Pillow; entry point `lidwork`; py>=3.11
  README.md           # install, per-OS setup, the honesty caveats above
  docs/DESIGN.md      # this file
```

### Backend interface (`base.py`)
```python
class Backend(ABC):
    def is_active(self) -> bool: ...        # real OS state, no caching
    def enable(self) -> None: ...           # start keeping-awake; snapshot first
    def disable(self) -> None: ...          # restore original state
    def needs_setup(self) -> bool: ...      # privileged one-time setup missing?
    def setup(self) -> None: ...            # install sudoers / scheduled task (may prompt once)
    def caveats(self) -> list[str]: ...     # warnings to show (e.g. GNOME override, "disables all sleep")
```
`get_backend()` returns the platform impl; unsupported platform → clear error.

### App behavior (`app.py`)
- On launch: `get_backend()`; if `needs_setup()` → menu shows "⚙ Run one-time
  setup" prominently and toggling triggers setup first.
- Icon = `is_active()`; menu items: status line (read-only), **Toggle**, any
  `caveats()` as disabled info rows, **Quit**.
- Poll `is_active()` on a timer (e.g. every 5 s) so external changes reflect.
- Toggle handler: `enable()`/`disable()`, then refresh icon; surface errors as a
  notification, never crash the tray.

### CLI (`cli.py`)
- `lidwork` → run tray app.
- `lidwork --status` → print ON/OFF + caveats, exit.
- `lidwork --on` / `--off` → headless toggle (for scripts/hotkeys).
- `lidwork --setup` → run privileged one-time setup.
- (Windows) `lidwork --_apply-helper` → internal, what the scheduled task runs;
  not for users.

---

## 4. State & config

- Config dir: platform-appropriate (`~/Library/Application Support/lidwork` on
  mac, `$XDG_CONFIG_HOME/lidwork` or `~/.config/lidwork` on Linux,
  `%LOCALAPPDATA%\lidwork` on Windows). A tiny helper, no `appdirs` dep needed.
- `state.json` (Windows-critical, harmless elsewhere):
  ```json
  {"desired": "on|off",
   "win_scheme_guid": "...",
   "win_restore_ac": 1, "win_restore_dc": 1}
  ```

---

## 5. Acceptance criteria (DoD)

Codex must deliver, and the review-gate verifies:

1. `pip install -e .` works on Python 3.11+; `lidwork --status` runs on the
   current OS without error.
2. **macOS (Claude can verify here):**
   - `lidwork --setup` installs a `visudo`-valid `/etc/sudoers.d/lidwork` (0440,
     root-owned); after setup, `--on`/`--off` flip `SleepDisabled` with **no**
     password prompt.
   - `--on` → `pmset -g` shows `SleepDisabled 1`; `--off` → `0`.
   - Tray icon changes state on toggle and reflects external `pmset` changes
     within one poll interval.
3. **Linux (user-tested, Codex writes):** `--on` spawns the `systemd-inhibit`
   child and `systemd-inhibit --list` shows our `lidwork` block; `--off` kills it.
   DE-power-manager warning appears when GNOME/KDE power daemon is detected.
4. **Windows (user-tested, Codex writes):** setup creates the `lidwork_apply`
   scheduled task (`RunLevel=Highest`); `--on` snapshots original AC/DC LIDACTION
   then sets both to 0 with no UAC prompt; `--off` restores the snapshotted
   values; state survives app restart.
5. `ruff check` clean. Type hints throughout. Google-style docstrings on the
   Backend ABC and public CLI funcs. No secrets, no network calls.
6. README documents: install, per-OS one-time setup, the macOS "disables all
   sleep" caveat, the Linux GNOME/KDE caveat, and how to fully uninstall
   (remove sudoers file / scheduled task).

---

## 6. Crash-safety & edge cases

- **macOS:** if the app dies while ON, `SleepDisabled` stays 1 — that's a
  recoverable, visible state (`pmset -g`); `--off` or reboot clears it. Acceptable.
  Document the one-liner to force-clear: `sudo pmset -a disablesleep 0`.
- **Linux:** if the app dies, the `systemd-inhibit` child dies with it (it's our
  child) → inhibitor auto-released. Good, no stuck state.
- **Windows:** the risk is dying while ON, leaving LIDACTION=0 and the snapshot
  only in state.json. `--off`/`--status` must reconcile from state.json on next
  launch; `lidwork --off` always works to restore. Document manual restore via
  Windows power settings.
- Toggling when already in the target state must be idempotent (no error).
- Setup run twice must be idempotent (overwrite/refresh, don't duplicate tasks).

---

## 7. Constraints for the implementer (task envelope)

- **ALLOWED PATHS:** everything under `~/Developer/lidwork/` (this is a fresh,
  isolated repo — nothing else exists to break).
- **FORBIDDEN:** do NOT `git commit/push`; do NOT add deps beyond `pystray` +
  `Pillow` without flagging; no `--dangerously-*`; no network calls; never write
  `/etc/sudoers.d/lidwork` without `visudo -c` validation first.
- **REPORT BACK:** files created, what was run, manual test results per-OS (note
  which you could/couldn't test), known risks.
- Claude reviews the diff (DoD §5), runs the macOS path live, runs `ruff`, then
  commits. Codex does not commit.

---

## 8. Codex review findings folded in

1. Linux: logind inhibitor is correct & sufficient at the logind layer; DE power
   managers may override → detect + warn (§2 Linux).
2. macOS: `disablesleep` kills *all* sleep, not just lid → be honest in UI/docs
   (§2 macOS).
3. Windows: must snapshot & restore original LIDACTION (AC+DC + scheme GUID);
   don't hardcode the restore value (§2 Windows, §6).
4. Tray base: pystray OK for a tiny tool but stale and weak on Linux; PySide6 is
   the documented fallback if Linux misbehaves (§3).
5. Windows privilege: one scheduled task `RunLevel=Highest` + state-file-driven
   helper, over running the whole tray app elevated (§2 Windows).
