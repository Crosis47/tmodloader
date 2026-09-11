# Container Changelog

This changelog records changes made by this maintained container fork. It does
not reproduce the tModLoader release notes. `VERSION` contains the container's
SemVer core, while each GitHub Release and exact image tag also identifies its
bundled tModLoader version and release channel. An image digest remains the
immutable deployment identifier.

## Unreleased

## 2.0.0 - 2026-09-10

### Breaking changes

- Admin secret files must contain an Argon2id hash; plaintext tokens are no
  longer accepted. Remove the old plaintext mount and leave
  `TMOD_WEB_TOKEN_FILE` empty to provision through the Web UI, or mount a
  pre-created Argon2id hash. Existing game worlds and settings are retained.

### Added

- First-run Web UI setup protected by a one-time code from container logs.
  Game startup waits until the admin hash is saved, then resumes automatically.
  Remote setup requires HTTPS or a localhost SSH tunnel.
- Include the Argon2 CLI and Python library, plus an interactive hash creation
  and rotation helper. Admin tokens accept 8–256 non-whitespace ASCII characters;
  only the salted hash is persisted with owner-only permissions.
- Verify setup, hash persistence across restart, and authentication using the
  container's installed dependencies and disposable integration-test volumes.

- Add `TMOD_WORLDEVIL` and a dashboard world-evil selector. Explicit Corruption
  or Crimson selections create missing worlds through the dedicated-server menu
  before normal startup. Existing worlds are retained; the WebUI explains how
  to choose an unused world name and apply changes to generate a different evil.

## 1.4.0 - 2026-09-10

### Fixed

- Start with a root-only initializer that repairs ownership and directory access
  for `/data` and `/backups`, then replaces itself with non-root `tini` and the
  existing `tml` supervisor/server process tree.

- Seed editable web settings from Compose on first boot and preserve saved web
  values over later Compose changes. Remove known client-only IDs from saved
  Workshop selections as well as the enabled mod list.

- Keep Workshop URL/ID import available without a Steam API key; only search and
  catalog browsing require the key.

- Readiness checks inspect the listening socket without connecting to the game;
  frequent dashboard polling no longer consumes anonymous player slots.

### Added

- Workshop Apply changes button sharing Configuration's draft review and
  blocking restart-progress dialog.

- Apply progress lists the names of client-only mods automatically removed from
  its draft or enabled list, retaining the notice through completion or failure.

- Filter explicitly client-only Workshop mods from the server enabled list on
  load; label and gray their search/lookup cards and prevent adding them.

- Overview lists confirmed loaded mods by display name and version from server
  loading records, independently of Workshop API access.

- Workshop controls stay locked with setup guidance until a readable, nonempty
  Steam API key is configured; console history labels show first-to-last output
  ranges, with unknown first times explicitly marked for legacy logs.

- Timestamped console-run selector and persistent archives of older console runs
  for browsing historical output across restarts.

- Blocking apply-progress dialog that prevents dashboard interaction during
  changes, resumes on reconnect, and can be dismissed after success or failure.

- Supervisor-reported apply stages, elapsed time, and completion/failure feedback
  directly on Configuration; paged browsing of the full retained console log.

- Grouped configuration sections with setting descriptions and running-value
  comparisons, plus an authenticated interactive game console with bounded
  output, command history, and stop-command confirmation.

- Opt-in authenticated in-container dashboard for server health, backup activity,
  archive verification, storage usage, and low-space warnings.
- Persistent staged configuration with explicit web-managed mode and confirmed
  game restart. Environment-managed deployments remain the default.
- Workshop search with an optional server-side Steam API key, URL/ID lookup,
  and staged mod/collection selection.
- Persistent last-success/failure backup status and configurable free-space reserve.

## 1.3.0 - 2026-09-08

### Added

- Container-native non-root backups using a /backups mount, with verified
  archives, build fingerprint recording, retention, and interval scheduling.
- Offline staged restore with a shared-data lock, preserved original data,
  and fail-closed startup after interrupted restores. No Docker socket or
  host Python installation is required.
- Archive corruption, unsafe-entry, image compatibility, retention, and restore
  failure regression tests.

## 1.2.1 - 2026-09-08

### Fixed

- Generate the `en_US.UTF-8` locale used by SteamCMD so international
  characters remain supported without its locale fallback warning.
- Report the mounted path owner, group, mode, and runtime group memberships
  when a required directory is not writable.
- Clarify and test that owner-only, group-only, ACL, and combined permission
  layouts are accepted whenever they grant the runtime identity real write and
  search access; Linux owner-class precedence is preserved.
- Include the missing world path in the first-launch warning and identify that
  initial world creation is expected.

## 1.2.0 - 2026-09-08

### Added

- A dedicated non-root `tml` runtime identity with fixed UID/GID `1000:1000`
  in published images and configurable identity build arguments for local
  images.
- Explicit startup diagnostics for mounted paths that are not writable by the
  runtime identity.

### Changed

- Replaced tmux session supervision with a server process group tracked
  directly by the entrypoint under `tini`.
- Console injection and scheduled saves now use a private runtime FIFO while
  preserving graceful shutdown and the server's real exit status.
- The supplied Compose deployment drops all Linux capabilities, prevents
  privilege escalation, and stores runtime control files on a bounded tmpfs.
- The real-server smoke test now verifies the non-root identity, PID 1 init,
  direct supervision, command injection, and hardened container settings.

## 1.1.1 - 2026-09-08

### Fixed

- Retry transient failures while downloading the upstream tModLoader release
  archive during image builds, preventing a single GitHub 5xx response from
  failing an otherwise valid release publication.

## 1.1.0 - 2026-09-08

### Added

- `TMOD_LOG_LEVEL=quiet|normal|debug` to control Docker console verbosity
  without reducing tModLoader's native logs.
- Persistent raw console logs for the current and previous server launch.
- Automatic raw-log tail replay after a non-zero server exit, configurable
  with `TMOD_CRASH_LOG_LINES`.

### Changed

- The default `normal` console collapses high-frequency world-generation
  progress, hides upstream launcher command chatter, and suppresses loopback
  healthcheck connection notices.

## 1.0.0 - 2026-09-08

### Added

- A container SemVer source of truth in `VERSION`.
- Composite GitHub Release and Docker tags that identify the container version,
  tModLoader version, and stable/preview channel.
- Automated GitHub Releases with the matching container changelog, exact and
  immutable image references, validation summary, and upstream release link.
- Real dedicated-server smoke tests in pull-request and publishing workflows.
- Docker health status based on the server session, startup log, and TCP port.
- Persistent tModLoader logs under `/data/tModLoader/Logs`.
- Recursive `collection:ID` expansion in `TMOD_MODS` with nested-collection
  support and a configurable item limit.
- Cached collection membership and `use-cache`/`strict` offline policies.
- `TMOD_PASS_FILE` support and a configurable graceful-shutdown timeout.
- Generated-configuration and Workshop regression tests.
- Automated stable and preview release discovery and publishing to GHCR.
- A manual workflow for building an exact upstream tModLoader release.
- `TMOD_MODS` as one source of truth for downloading, updating, and enabling
  Workshop mods.
- Workshop manifest comparison so SteamCMD runs only for missing or outdated
  mods.

### Changed

- Public GHCR tags are now assigned only after the exact candidate digest
  passes script tests and a real server startup/shutdown test.
- Generated server settings are validated before launch.
- Password values are redacted, generated config permissions are restricted,
  and password variables are removed before tModLoader logs its environment.
- Compose now separates the host port from the container port and sources
  routine settings from `.env`.
- Scheduled autosave commands can be disabled with an interval of `0`.

### Fixed

- Pinned the runtime to Ubuntu 24.04 and verified the bundled .NET runtime at
  build time, preventing incompatible base-image updates from producing broken
  containers.
- Removed automation that repeatedly rewrote the Dockerfile and fought between
  stable and preview releases.
- Made generated configuration, shutdown, autosave, and command injection more
  reliable.
