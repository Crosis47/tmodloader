# Container Changelog

This changelog records changes made by this maintained container fork. It does
not reproduce the tModLoader release notes. Image tags such as
`v2026.07.3.0` identify the bundled upstream tModLoader release; the same tag
can be rebuilt when this container receives a fix. An image digest is the
immutable identifier.

## Unreleased

### Added

- Real dedicated-server smoke tests in pull-request and publishing workflows.
- Docker health status based on the server session, startup log, and TCP port.
- Persistent tModLoader logs under `/data/tModLoader/Logs`.
- Recursive `collection:ID` expansion in `TMOD_MODS` with nested-collection
  support and a configurable item limit.
- Cached collection membership and `use-cache`/`strict` offline policies.
- `TMOD_PASS_FILE` support and a configurable graceful-shutdown timeout.
- Generated-configuration and Workshop regression tests.

### Changed

- Public GHCR tags are now assigned only after the exact candidate digest
  passes script tests and a real server startup/shutdown test.
- Generated server settings are validated before launch.
- Password values are redacted, generated config permissions are restricted,
  and password variables are removed before tModLoader logs its environment.
- Compose now separates the host port from the container port and sources
  routine settings from `.env`.
- Scheduled autosave commands can be disabled with an interval of `0`.

## 2026-09-08 - Maintained fork baseline

### Added

- Automated stable and preview release discovery and publishing to GHCR.
- A manual workflow for building an exact upstream tModLoader release.
- `TMOD_MODS` as one source of truth for downloading, updating, and enabling
  Workshop mods.
- Workshop manifest comparison so SteamCMD runs only for missing or outdated
  mods.

### Fixed

- Pinned the runtime to Ubuntu 24.04 and verified the bundled .NET runtime at
  build time, preventing incompatible base-image updates from producing broken
  containers.
- Removed automation that repeatedly rewrote the Dockerfile and fought between
  stable and preview releases.
- Made generated configuration, shutdown, autosave, and command injection more
  reliable.
