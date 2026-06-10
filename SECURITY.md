# Security

`lidwork` toggles OS sleep/lid settings, which requires one-time privileged
setup. This document describes the threat model, the privilege design, and how
to verify what you download.

## Threat model

In scope (what the design defends against):

- **Post-setup local tampering** by same-user, lower-privilege code trying to
  abuse the privileged path that setup installs (the elevated Windows scheduled
  task, the macOS `sudoers` rule).
- **PATH / binary hijacking** of the elevated helper.
- **Argument / command injection** through values that cross the privilege
  boundary (usernames, power-scheme identifiers, file paths).
- **Tampered downloads** — see "Verifying your download" below.

Out of scope:

- A user who knowingly runs an already-malicious binary, or who is already
  root/Administrator. `lidwork` cannot protect a machine whose owner installs
  malware.
- Physical attackers, kernel exploits, and supply-chain compromise of upstream
  dependencies beyond the pinning/provenance described here.

## Privilege model

`lidwork` runs as your normal user. Only two operations need elevation, both
gated behind an explicit one-time `lidwork --setup`:

- **macOS** — installs `/etc/sudoers.d/lidwork` granting NOPASSWD for *exactly*
  `/usr/bin/pmset -a disablesleep 0` and `... 1` — nothing else. The file is
  created, validated with `visudo`, and installed (`0440 root:wheel`) entirely
  inside the single elevated step, so no user-owned file is trusted across the
  privilege boundary. The account name is read from the passwd database and
  charset-validated.
- **Windows** — creates one scheduled task (`lidwork_apply`, highest privileges).
  For packaged builds, setup copies the executable into
  `%ProgramFiles%\lidwork` (admin-writable only) and points the task there, so
  the elevated task can't be repointed at a user-writable binary. The elevated
  helper calls system tools by absolute `System32` path, validates the power
  scheme GUID, and only ever sets `LIDACTION` to a value in `{0,1,2,3}`.
- **Linux** — no elevation. A `systemd-inhibit` process is held while active.

To remove the privileged setup, see "Uninstall" in the README.

## Known limitations

- **Windows, separate admin account.** Setup assumes the account that approves
  the UAC elevation is the same account that will use `lidwork`. If you run as a
  standard user and elevate with a *different* administrator account, the
  scheduled task may be registered for the admin identity rather than yours, and
  `--on`/`--off` may not drive the intended task. Single-user laptops where the
  user is the administrator (the primary target) are unaffected.
- **Linux** lid handling is best-effort (see README) and is not a security
  boundary.

## Verifying your download

Releases are **unsigned** (no paid code-signing certificate). Instead, every
release provides independent integrity and authenticity:

1. **Checksums** — each release includes a `SHA256SUMS` file. Verify, e.g.:

   ```bash
   # macOS / Linux
   shasum -a 256 -c SHA256SUMS        # (or: sha256sum -c SHA256SUMS)
   ```

2. **Build provenance** — artifacts carry a signed GitHub build attestation.
   Verify that a file was built by this repo's release workflow:

   ```bash
   gh attestation verify <downloaded-file> --repo DinoZawrik/lidwork
   ```

On first launch you will still see an OS "unsigned" prompt; the bypass steps are
in the README. Verifying the checksum/provenance first is recommended.

## Supply chain

- GitHub Actions are pinned to commit SHAs (not mutable tags).
- Workflow tokens are least-privilege: `contents: read` by default; only the
  release `publish` job gets `contents: write`; build jobs get
  `id-token`/`attestations: write` solely for provenance.
- Runtime/build dependencies are version-bounded in `pyproject.toml`.

## Reporting a vulnerability

Open a GitHub issue (or, for sensitive reports, a private security advisory) at
<https://github.com/DinoZawrik/lidwork>. Please include repro steps and the
affected platform.
