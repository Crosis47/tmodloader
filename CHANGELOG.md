# Container Changelog

All notable container changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and container versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog records changes made by this maintained container fork. It does
not reproduce the tModLoader release notes. `VERSION` contains the container's
SemVer core. GitHub Releases and image tags use that version, with `-preview`
for preview builds. Release notes identify the default runtime channel. An image
digest identifies the container tools; persistent runtime metadata identifies the
installed tModLoader release.

## [Unreleased]

## [3.5.0] - 2026-09-24

### Added

- Set or remove the server password through Configuration with hidden values and reviewed draft application.

- Capture character joins and connection addresses through a server-only helper, group history by name, and retain per-address ban controls without requiring character artwork.
- Persist server-wide and per-world character join history, with searchable player cards, visit counts, and first/last join dates. Track live joins without an open dashboard and keep world history across switches.
- Retain observed connection identifiers and offer reviewed bans from player history after someone disconnects. Clearly distinguish character names and IP/Steam ban targets from unavailable verified account names.
- Add confirmed per-address unban controls, collapsible multi-address lists, and paging controls that hide when unavailable.
- Show the running Workshop selection as cards for easier draft removals, including fallback cards when Steam details are unavailable.

### Changed

- Install tModLoader and its native .NET runtime into persistent storage on first startup instead of bundling them in the image. Publishing uses fixed stable/preview channels without upstream release discovery or game-version build inputs.


## [3.4.1] - 2026-09-22

### Added

- Notify administrators at dashboard login when a newer container release is
  available, with release notes and guidance for updating the container.
- Cache container-release checks, respect stable/preview image channels, and
  keep failed checks or other open dialogs from interrupting login.

### Fixed

- Keep Docker Hub overview content below its 25,000-byte limit by linking detailed
  reference sections when necessary, preserving setup instructions and published release notes.

## [3.4.0] - 2026-09-21

### Added

- Download and cache supported tModLoader releases at startup without replacing
  the container image, with stable/preview channels and optional version pins.
- Stage Workshop changes and validate enabled mods, dependencies, and a copied
  world before switching runtimes; retain the existing runtime and mods if checks fail.
- Recover interrupted updates and automatically restore the previous runtime and
  data if updated startup fails its health check.
- Dashboard update notices, release checks, diagnostics, and confirmed game-only
  restart and recovery actions with step-by-step progress dialogs.
- Delete recovery checkpoints after testing an update; successful recovery now
  deletes its checkpoints automatically after the restored game is healthy.
- Optional in-game new-release announcements, saved immediately and sent once per
  release even when the dashboard is closed.

### Changed

- Publish container images on container version changes or manual runs; remove
  scheduled upstream release polling now that runtime updates happen in the server.
- Record the selected runtime in backup compatibility metadata.
- Show update controls only when relevant and explain each stage in a collapsed workflow guide.
- Support nested mod-configuration files and group their paths in the editor.
- Upgrade QEMU setup to its Node.js 24 action and pin workflow runners to Ubuntu 24.04.
- Name the AMD64 SteamCMD build stage explicitly to avoid the constant-platform warning.

### Fixed

- Check data-volume writability before creating updater control files, preserving
  the precise read-only volume startup diagnostic.
- Cache internal bundled library symlinks safely, including the SDL alias created
  during tModLoader startup, while continuing to reject linked game-data paths.
- Preserve the game password during dashboard runtime restarts and rollback.

## [3.3.0] - 2026-09-21

### Added

- Edit existing mod configuration files from the dashboard, with syntax checks for
  JSON, YAML, TOML, INI, and XML, stale-file protection, and atomic saves.
- Delete unused worlds after confirmation, protecting running and draft-selected worlds.
- Cancel saved configuration drafts directly from the saved-change review dialog.

- Workshop API key entry with Steam validation, admin-token-based encrypted persistent storage,
  replacement controls, and an explanation of how the key is stored.
- Workshop dependency checks, including nested requirements and collections,
  with an Add / Cancel review before staging missing server items.

- Automatically sync the README and published release changes to Docker Hub's
  Overview, including working screenshot links and documentation-only updates.

- Optional Docker Hub publishing of verified multi-platform releases, with
  digest verification, protected version tags, and retries without rebuilding.

### Changed

- Organize administration API routes into named feature handlers and document
  startup, configuration, and recovery coordination in a contributor code map.

### Fixed

- Preserve accumulated client-only mod removal notices across draft edits.
- Consistently block configuration changes during active administration or backup operations.
- Restore readable punctuation in dashboard labels and install all mod-editor test dependencies in CI.

## [3.2.0] - 2026-09-16

### Added

- Expandable backup details with archived worlds, running-world provenance, mods,
  timestamps, sizes, and runtime compatibility. Inspect older archives to recover
  available details from their contents.
- Prepare a verified backup copy for a different container build when the
  tModLoader release matches, preserving the original archive. Retention keeps
  archives made by other builds.

- Server Journey defaults and optional per-world overrides on the Worlds page,
  shown only for confirmed Journey worlds; overrides persist across world switches
  and container restarts.
- A saved-change review dialog listing each setting's running and saved values,
  including world and Journey settings outside Configuration.
- Expand saved-world entries to see size, difficulty, evil, seed, creation date,
  Hardmode status, special seeds, spawn/dungeon coordinates, and file details.
  Show current session uptime and persistent cumulative uptime per world, starting
  when the world finishes loading.

### Changed

- Move backup preparation and restore actions into expanded archive details;
  review and confirm restores in a popup.
- Move world creation into a New World dialog and Journey permissions into world
  actions, removing both sections from the general Configuration form.
- Hide the switch action for the current world and label other world actions Switch.

### Fixed

- Normalize the backup helper launch header during image builds so Windows
  checkouts can run inspection; show inspection progress and errors beside archives.
- Show the saved-changes reminder only when the draft differs from running settings,
  rather than whenever a draft file exists.
- Preserve focus, text selections, and unfinished profile/playthrough names during
  background refreshes; keep world creation fields enabled while polling.
- Automatically scale dashboard storage and file sizes to readable binary units,
  promoting values at 1,000 (for example, GiB to TiB).

## [3.1.1] - 2026-09-16

### Changed

- Present release notes as dated, categorized changes following Keep a Changelog,
  with image and validation details in a separate expandable section.

### Fixed

- Fix creation of worlds with spaces in their names, preserving the configured
  filename and mod sidecar without replacing existing worlds.
- Show live admin-token validation and matching indicators during first-run setup.
  Keep submission disabled until all fields are ready, and show progress,
  incorrect-code errors, and connection recovery guidance.

## 3.1.0 - 2026-09-15

### Changed

- Allow dashboard HTTP access from RFC 1918 source addresses and loopback;
  require HTTPS for other sources on every request without a startup crash loop.
- Enable direct LAN dashboard access with automatic IP/port origins, preserving
  setup-code authentication and cross-origin checks. Add explicit single-proxy
  trust for original client addresses and HTTPS detection.

## 3.0.1 - 2026-09-15

### Changed

- Simplify image and GitHub Release tags to matching container versions (`3.0.1`
  and `3.0.1-preview`), with tModLoader versions in release notes and OCI labels.
- Publish only numbered versions and the `latest`, `stable`, and `preview` aliases.
- Require a container version bump for each newly packaged upstream release.

## 3.0.0 - 2026-09-15

### Changed

- Enable the WebUI by default; set TMOD_WEB_ENABLED=0 for unattended game-only startup.
  Simplify Compose to ports, persistent storage and an environment file, using
  Docker default initialization capabilities and the image privilege drop.
- Default first-run startup waits for WebUI admin setup before starting the game
  server. Set `TMOD_WEB_ENABLED=0` to retain unattended game-only startup.
- Refresh the README with a dashboard screenshot gallery and project attribution.

## 2.2.0 - 2026-09-13

- Combine backups and recovery, and expand the read-only Overview with world, player, settings, profile and recovery summaries.

- Add Playthroughs to save and switch world, Journey permission and mod selections together.

- Add named mod profiles with running/draft capture, guarded loading, rename, replacement and deletion.

### Added

- Attention banner for pending drafts and recovery issues, amber unsaved-setting
  cards and blue saved-but-not-applied cards. Clarify player command activity.

- Worlds page with saved-world inventory, guarded creation and switching,
  generation options, and the shared review/apply progress flow.

- Player Management page with fresh native-console player queries, name filters,
  reviewed kick/ban actions, announcements and bounded activity history. Persist
  native bans under `/data/tModLoader/banlist.txt` for generated configurations.

- Recovery dashboard with verified archive previews, confirmed supervised
  restore, retained original data, startup retry and game health progress.
  Restores preserve current admin credentials and enforce existing archive,
  build, free-space and interrupted-restore safeguards.

## 2.1.1 - 2026-09-12

### Fixed

- Enable the publisher's containerd image store so AMD64 and ARM64 candidates
  can be tested under the same multi-platform digest before release publication.
- Remove obsolete plaintext admin-token upgrade warnings from the documentation
  and simplify the invalid-hash error. Admin credentials require Argon2id hashes.

## 2.1.0 - 2026-09-11

### Added

- Native Linux ARM64 image alongside AMD64, including native .NET and
  DepotDownloader for anonymous Steam Workshop downloads without x86 emulation.
- Staged native Workshop updates that preserve cached mods on failure and track
  downloaded manifests for cache reuse.
- Native ARM64 CI coverage, executable architecture checks, live Workshop
  download/cache tests, and dual-architecture validation before publication.

## 2.0.0 - 2026-09-11

### Added

- First-run Web UI setup protected by a one-time code from container logs.
  Game startup waits until the admin hash is saved, then resumes automatically.
  Remote setup requires HTTPS or a localhost SSH tunnel.
- Include the Argon2 CLI and Python library, plus an interactive hash creation
  and rotation helper. Admin tokens accept 8–256 non-whitespace ASCII characters;
  only the salted hash is persisted with owner-only permissions.
- Verify setup, hash persistence across restart, and authentication using the
  container's installed dependencies and disposable integration-test volumes.
- Preserve normal console filtering across world creation and the subsequent
  game launch; complete launcher output remains available in the raw log.

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

[Unreleased]: https://github.com/Crosis47/tmodloader/compare/3.4.1...HEAD
[3.4.1]: https://github.com/Crosis47/tmodloader/compare/3.4.0...3.4.1
[3.4.0]: https://github.com/Crosis47/tmodloader/compare/3.3.0...3.4.0
[3.3.0]: https://github.com/Crosis47/tmodloader/compare/3.2.0...3.3.0
[3.2.0]: https://github.com/Crosis47/tmodloader/compare/3.1.1...3.2.0
[3.1.1]: https://github.com/Crosis47/tmodloader/compare/3.1.0...3.1.1
