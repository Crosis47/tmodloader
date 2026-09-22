# Code and process map

## Start here

| Concern | Entry point | Next step |
| --- | --- | --- |
| Container permissions | `container-init.sh` | Repairs volume ownership, then drops privileges with `setpriv` |
| Startup and supervision | `entrypoint.sh` | Settings, Workshop preparation, admin startup, game startup, request loop |
| Runtime updates | `runtime_updates.py`, `admin_updates.py` | Cold-start staging, copied-world probe, persistent runtime selection and recovery journal; cached release notices |
| Game launch and logs | `run-server.sh` | `create_world.py` → upstream launcher; output through `console_tee.py` and `log-filter.sh` |
| HTTP access and authentication | `admin_server.application` | `admin_access`, `admin_auth`, then `api` |
| API routing | `admin_server.api` | Named feature handlers; handlers retain their validation and locks |
| Settings | `admin_settings.py` | Validation, Compose defaults, saved settings and pending draft |
| Feature rules | `admin_worlds`, `admin_profiles`, `admin_playthroughs`, `admin_journey`, `admin_players` | Filesystem state or native game commands |
| Browser | `web/app.js` | `api()` requests, feature render/refresh functions, event handlers |
| Container backup CLI | `container-backup.py` (`tmod-backup`) | Backup coordination plus archive primitives in `backup.py` |
| Host backup CLI | `backup.py` | Docker orchestration plus the same archive primitives |

Python names above refer to the same-named files at the repository root.
`Dockerfile` explicitly copies runtime files; adding a module also requires
updating that copy list. Static asset paths are allowlisted in `application`.

## Trace a settings change

1. Browser edits are local until the user saves. `POST /api/settings` enters
   `application` for access/authentication and JSON checks, then `api`, then
   `save_settings`.
2. Under `STATE_LOCK`, the handler checks for an active operation and compares
   the draft revision. It validates and filters the values, writes `PENDING`,
   and records removed client-only mod notices. Saving does not restart the game.
3. A confirmed `POST /api/apply` enters `operation_request`, which checks the
   draft revision, recovery state and pending world before calling `start_job`.
4. `start_job` acquires `OPERATION` and starts `job_runner`. For apply, restore
   and retry, that worker writes `admin-request` in the runtime directory.
5. The request loop near the end of `entrypoint.sh` consumes that file and calls
   `perform_admin_apply` or `perform_recovery`. Apply stops the game, promotes
   settings, resolves mods, starts the game, and checks health.
6. The supervisor publishes `admin-progress` and `admin-result`. `job_runner`
   accepts only records matching its request ID, updates `JOB`, and releases
   `OPERATION` on completion or failure. The browser polls to display progress.

`ACTIVE` is the saved configuration; `PENDING` is the saved draft;
`admin-effective.json` describes the running configuration. These are different
states. Compose seeds missing saved values at boot; intentionally empty saved
values still take precedence. See `configuration()` and `admin_settings.boot_values()`.

## Operation boundaries

- `STATE_LOCK` serializes API checks and mutations. `operation_busy()` includes
  both API jobs and the backup status written by CLI/scheduled backups. It only
  reads status; it does not acquire a lock.
- `OPERATION` prevents overlapping administration jobs. The worker releases it
  in `finally`; keep this ownership explicit when changing error handling.
- Backup, verification, preview, inspection and preparation jobs invoke
  `tmod-backup`; apply, restore and retry use the supervisor request files.
- The shell supervisor owns the game process and stop/start lifecycle. An API
  request being accepted does not establish that the game restarted successfully.
- Recovery also has persistent interruption records. Do not replace these with
  the in-memory `JOB`, which is lost when the admin process restarts.

## Maintainability review (2026-09-20)

The backend already separates feature rules into small modules. The main risk
is coordination code accumulating in the API, browser and supervisor.

Completed in this pass:

- Reduced the 181-line API dispatcher to explicit route-to-handler calls.
  Substantial routes now have named handlers; validation order and lock scopes
  stay with their original operations.
- Centralized the repeated API-job/CLI-backup busy check.
- Centralized accumulation of pending client-mod removal notices shared by
  settings, profiles and playthroughs.

Remaining priorities:

| Priority | Hotspot | Why it is difficult to follow | Suggested next change |
| --- | --- | --- | --- |
| High | `web/app.js` | Shared state, timers, rendering and event registration span roughly 1,400 lines; several features invoke the Apply button's `onclick` as a workflow | Give the apply workflow a named entry point, then separate feature sections with explicit state ownership; preserve browser regression tests |
| Medium | `entrypoint.sh`: apply/recovery | Both paths handle stopping, restarting, health waits and failure cleanup, with different recovery obligations | Extract only genuinely identical lifecycle steps after adding shell failure-path coverage |
| Medium | `admin_server.job_runner` | Direct subprocess jobs and supervisor-file jobs share one worker | Separate execution mechanisms while keeping result reporting and lock release in one owner |
| Medium | `admin_profiles.change` / `admin_playthroughs.change` | Catalog revision checks, naming, confirmation and storage limits are nearly duplicated | Share narrowly scoped catalog validation helpers; keep world and Journey staging rules explicit |
| Low | `admin_world_metadata.read_metadata` | Binary fields must be read in a strict sequence | Preserve the visible format order; use named field groups if more header versions are added |

These are maintainability findings, not verified runtime defects. Moving code
into more files alone will not resolve implicit state or lifecycle coupling.
No broad dead-code removal was attempted: shell/CLI entry points, browser event
callbacks and Docker copy lists make a text search for references insufficient.

## Regression checks

Run `python -m unittest discover -s tests -p 'test_admin*.py'` for request access,
confirmation, stale revisions, settings, worlds, profiles, playthroughs,
players and recovery. Python needs `argon2-cffi` and `waitress`.

Browser changes require the relevant `tests/admin-*-test.cjs` scripts. Preserve
`refreshWouldInterrupt` checks both before a background request and before its
render: users can start typing while a request is in flight. Explicit refresh
and background polling deliberately have different behavior.

Supervisor or backup lifecycle changes also require the Docker runtime and
integration checks listed in [Contributing](../CONTRIBUTING.md). Python mocks do
not verify an actual game stop, restart or restore.

## Runtime update transaction

The supervisor takes the data lock before `runtime_updates.py boot`, which
recovers an interrupted switch or consumes confirmed recovery queued by the API.
After settings and first-run authentication, `prepare` caches the image runtime,
checks releases, and stages Workshop content against copied data. The native
candidate must load every enabled mod, reach readiness and exit cleanly.

A journal is written before replacing live mods and runtime selection. It remains
until the supervisor verifies live health. A crash before that confirmation
restores the immutable `before` copy on the next boot. A failed live startup also
restores the checkpoint and sets an update hold. Runtime binaries and checkpoints
live under `.tmod-control/updates` and are excluded from normal backup archives;
`admin_backup_details` derives backup identity from the selected runtime.

Upstream logs are relative to the executable. `route_logs` redirects them to the
trial during validation and restores the live log path afterward and at boot.
Never run the candidate with the live world, live Workshop tree, or live log path.
The read-only release checker writes `check.json`, independently of the startup
worker's `status.json`; dashboard polling must never launch an installation.

Dashboard `POST /api/updates/restart` queues a confirmed `runtime-update` supervisor job. `perform_runtime_update` saves/stops only the game, runs queued recovery or startup update preparation, reloads saved settings, drains old console commands, and checks live health. Candidate startup failure restores the checkpoint and retries the prior runtime. The dashboard and container stay running; failed preparation leaves recovery controls available.
