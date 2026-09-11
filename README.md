# tModLoader Dedicated Server Container

[![Publish](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-publish.yml?branch=master&logo=github&label=image%20publisher&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-publish.yml)
[![CI](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-ci.yml?logo=github&label=docker%20CI&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-ci.yml)

[GitHub repository](https://github.com/Crosis47/tmodloader) |
[GHCR images](https://github.com/Crosis47/tmodloader/pkgs/container/tmodloader) |
[Releases](https://github.com/Crosis47/tmodloader/releases) |
[Container changelog](CHANGELOG.md) |
[Contributing](CONTRIBUTING.md) |
[Security](SECURITY.md)

This container runs a configurable tModLoader dedicated server with persistent
worlds, mods, configuration, and logs. Steam Workshop mods and collections can
be managed from one environment variable, and the published images are tested
by starting a real server before their public tags are updated.

## Maintained hard fork

This repository is a **hard fork of
[JACOBSMILE/tmodloader1.4](https://github.com/JACOBSMILE/tmodloader1.4)**. It is
independently maintained and is not an upstream mirror. The fork preserves the
original project's foundation and license while adding new features and fixes
for long-standing container, dependency, automation, configuration, shutdown,
and Workshop-management bugs.

Changes made here should not be assumed to exist in the original repository,
and this project is not affiliated with Re-Logic or the tModLoader team.

## Features

- Stable, preview, and exact-version images published to GHCR.
- Candidate-image gating with script tests and a real server smoke test.
- One `TMOD_MODS` setting for downloading, updating, and enabling Workshop mods.
- Recursive Steam Workshop collection expansion and cached-offline startup.
- Persistent worlds, mod configuration, Workshop content, and server logs.
- Configurable quiet, normal, and debug Docker console output with automatic
  crash-tail replay and persistent raw logs.
- Docker health status based on the supervised server process, log, and TCP port.
- Validated environment-based server configuration or an optional custom file.
- Password redaction and file-based password support.
- Scheduled saves, console command injection, and graceful shutdown.
- Root-assisted persistent-directory repair followed by non-root execution with
  `tini`, direct process supervision, and hardened Compose capability defaults.

## Requirements

- Docker Engine with the Compose plugin, or Docker Desktop.
- Enough memory for the selected world and mod pack; requirements vary greatly
  between mod collections.
- Host storage for persistent data and backups. The container prepares its
  ownership automatically at startup.
- The configured TCP port allowed through the host firewall when remote players
  will connect.

## Quick start with Docker Compose

### 1. Get the deployment files

```bash
git clone https://github.com/Crosis47/tmodloader.git
cd tmodloader
```

Create your private `.env` from the supplied template:

```bash
# Linux, macOS, or Git Bash
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

The `.env` file is excluded from Git. Do not commit it if it contains a server
password or other deployment-specific information.

Optionally create the bind-mounted directories before starting. Compose also
creates them when they do not exist:

```bash
mkdir -p ./data ./backups
```

On every start, the container assigns these trees to its `tml` runtime identity
and ensures that identity can access their directories. On Linux bind mounts,
this changes the corresponding host ownership to UID/GID `1000:1000` for the
published image. Review the mount targets before starting the container.

### 2. Configure the server

Open `.env` and, at minimum, review these values:

```dotenv
TMOD_HOST_PORT=7777
TMOD_PORT=7777
TMOD_MODS=
TMOD_LOG_LEVEL=normal
TMOD_WORLDNAME=Docker
TMOD_WORLDSIZE=3
TMOD_DIFFICULTY=1
TMOD_MAXPLAYERS=8
TMOD_PASS=
```

- Leave `TMOD_MODS` empty for an unmodded tModLoader server, or add Workshop
  IDs as described under [Workshop mods and collections](#workshop-mods-and-collections).
- Set a unique `TMOD_PASS`. An empty value or `N/A` disables authentication.
- `TMOD_HOST_PORT` is the port players contact on the Docker host.
- `TMOD_PORT` is the port tModLoader listens on inside the container. Compose
  maps the host value to this value automatically.
- The world size and difficulty settings are used only when a world does not
  already exist.

Values containing `#`, quotes, or dollar signs should be quoted according to
Docker Compose `.env` syntax. After editing, verify the rendered configuration:

```bash
docker compose config
```

### 3. Pull and start

```bash
docker compose pull
docker compose up -d
docker compose logs --tail=100 --follow tmodloader
```

The first start can take several minutes while SteamCMD initializes, mods are
downloaded, and the world is generated. Stop following logs with `Ctrl+C`; that
does not stop the container.

Check Docker's health result:

```bash
docker inspect --format '{{.State.Health.Status}}' tmodloader
```

Once it reports `healthy`, connect to the Docker host's address and
`TMOD_HOST_PORT`.

## Persistent data

The supplied Compose file binds `./data` on the host to `/data` in the
container:

```text
data/
├── steamMods/
│   └── steamapps/workshop/
└── tModLoader/
    ├── Logs/
    ├── ModConfigs/
    ├── Mods/
    │   ├── collection-cache/
    │   └── enabled.json
    └── Worlds/
```

Replacing the container does not remove this directory. Worlds, downloaded
Workshop items, enabled-mod state, mod configuration, logs, and collection
membership cache therefore survive normal upgrades.

At startup, a root-only initialization stage recursively assigns `/data` and
`/backups` to `tml:tml` without following symlinks or crossing into nested
filesystems. It also adds owner read/write/search access to directories that
lack it. Entries that already have the correct ownership and directory access
are left unchanged, avoiding needless metadata rewrites on large Workshop
trees. After the repair, startup drops permanently to `tml` and performs a real
create/write probe. A read-only or otherwise unsupported mount therefore fails
before the server starts with the affected path, owner/group, and mode.

## Runtime security and process model

Published images start a small initializer as root and run `tini`, SteamCMD,
tModLoader, the supervisor, the admin page, and scheduled backups as the
dedicated `tml` user with UID/GID `1000:1000`. The initializer changes identity
and replaces itself with `tini`, so no root wrapper remains. `tini` is PID 1 and
reaps orphaned processes, while the entrypoint directly tracks the server
process group and feeds console commands through a private FIFO. Compose drops
all Linux capabilities except the five required to repair ownership/access and
switch UID/GID. The identity switch clears those capabilities, and
`no-new-privileges` prevents the runtime from reacquiring them. Compose also
provides a bounded temporary filesystem for runtime control files. That `/tmp`
filesystem permits executable mappings because MonoMod creates a short-lived
native helper there during startup; it remains isolated, size-limited,
`nosuid`, and `nodev`.

The image must declare root as its initial Docker user for this initialization
stage. Consequently, arbitrary `docker exec` commands default to root even
though the running process tree is non-root. Use `docker exec --user tml:tml`
or `docker compose exec --user tml:tml` for interactive commands. The supplied
`healthcheck`, `inject`, and `tmod-backup` commands also drop to `tml`
themselves when Docker invokes them as root.

If a Linux host requires a different fixed identity, build a local image with
`TMOD_UID` and `TMOD_GID` build arguments. The initializer resolves the `tml`
account in that image and applies its selected numeric UID/GID automatically.
Do not override the container user: initialization must begin as root, and the
image drops privileges before launching `tini` and the application.

## Configuration model

Compose reads `.env` and passes the supported values into the container. The
precedence rules are:

1. With `TMOD_USECONFIGFILE=No`, the container validates the server settings
   and writes a fresh generated configuration on every start.
2. `TMOD_PASS_FILE`, when configured in generated-config mode, overrides
   `TMOD_PASS`.
3. With `TMOD_USECONFIGFILE=Yes`, the mounted `customconfig.txt` controls the
   Terraria server settings. Container controls such as mods, autosave, and
   shutdown still apply.
4. A non-empty `TMOD_MODS` replaces the deprecated `TMOD_AUTODOWNLOAD` and
   `TMOD_ENABLEDMODS` behavior.

Generated settings reject invalid numeric ranges, unsafe world paths, and
multiline values before the server starts. The password is redacted from
startup output, the generated file is mode `0600`, and password variables are
removed before tModLoader logs its process environment.

### Container and Workshop settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `TMOD_MODS` | empty | Comma-separated mod IDs and `collection:ID` entries to update and enable. |
| `TMOD_MOD_OFFLINE_POLICY` | `use-cache` | Use complete cached mods during a Steam outage; `strict` requires successful verification. |
| `TMOD_COLLECTION_MAX_ITEMS` | `1000` | Maximum recursively expanded collection items and nested collections. |
| `TMOD_DOWNLOAD_RETRIES` | `3` | SteamCMD attempts for required downloads or updates. |
| `TMOD_DOWNLOAD_RETRY_DELAY` | `10` | Seconds between SteamCMD attempts. |
| `TMOD_AUTOSAVE_INTERVAL` | `10` | Minutes between save commands; `0` disables scheduled commands. |
| `TMOD_SHUTDOWN_MESSAGE` | `Server is shutting down NOW!` | Chat message sent during a Docker stop. |
| `TMOD_SHUTDOWN_TIMEOUT` | `90` | Seconds allowed for graceful shutdown before the directly supervised server process group is terminated. |
| `TMOD_LOG_LEVEL` | `normal` | Docker console detail: `quiet`, `normal`, or `debug`. |
| `TMOD_CRASH_LOG_LINES` | `200` | Raw console lines replayed after a non-zero exit in quiet/normal mode; `0` disables replay. |
| `TMOD_USECONFIGFILE` | `No` | Use `/terraria-server/customconfig.txt` when set to `Yes`. |

### Generated server settings

| Variable | Default | Valid values and behavior |
| --- | --- | --- |
| `TMOD_MOTD` | `A tModLoader server powered by Docker!` | Message shown to joining players. |
| `TMOD_PASS` | `docker` in the image; `N/A` in Compose when empty | Server password; empty/`N/A` disables it in the supplied Compose deployment. |
| `TMOD_PASS_FILE` | empty | Mounted password-file path; overrides `TMOD_PASS` in generated-config mode. |
| `TMOD_MAXPLAYERS` | `8` | `1` through `255`. |
| `TMOD_WORLDNAME` | `Docker` | World display name and filename; path separators are rejected. |
| `TMOD_WORLDSIZE` | `3` | `1` small, `2` medium, `3` large; new worlds only. |
| `TMOD_WORLDEVIL` | `random` | `random`, `corruption`, or `crimson`; new worlds only. Explicit evil uses supervised menu creation before normal server startup. |
| `TMOD_WORLDSEED` | `Docker` | Seed used for a new world. |
| `TMOD_DIFFICULTY` | `1` | `0` normal, `1` expert, `2` master, `3` journey; new worlds only. |
| `TMOD_SECURE` | `0` | `0` disabled or `1` enabled. |
| `TMOD_LANGUAGE` | `en-US` | Language code such as `en-US`, `de-DE`, or `pt-BR`. |
| `TMOD_NPCSTREAM` | `60` | NPC streaming range from `0` through `1000`. |
| `TMOD_UPNP` | `0` | `0` disabled or `1` enabled; explicit Docker port publishing is recommended. |
| `TMOD_PRIORITY` | `1` | Process priority from `0` realtime through `5` idle. |
| `TMOD_PORT` | `7777` | Internal TCP listening port from `1` through `65535`. |

Journey permission variables are included in `.env.example`. Each accepts `0`
(locked), `1` (host only), or `2` (everyone).

## Workshop mods and collections

Every Steam Workshop item has an ID in its URL. For example, Calamity Mod uses
`2824688072`. Use one comma-separated `TMOD_MODS` value to control both download
and enablement:

```dotenv
TMOD_MODS=2824688072,2824688266
```

Prefix a collection ID with `collection:`. Nested collections are expanded
recursively:

```dotenv
TMOD_MODS=2824688072,collection:3443710509
```

At startup, the container:

1. Expands collections and filters their public items to tModLoader Workshop
   application `1281930`.
2. Deduplicates direct and collection-derived IDs.
3. Compares local Workshop manifests with Steam.
4. Downloads only missing or outdated items.
5. Atomically writes the resolved `.tmod` names to `enabled.json`.

Collection membership is cached under
`/data/tModLoader/Mods/collection-cache`. With the default
`TMOD_MOD_OFFLINE_POLICY=use-cache`, the server can start during a Steam API or
SteamCMD outage only when the collection membership and every requested mod are
already cached. It will never silently ignore a requested mod that is missing.
Use `strict` when any inability to verify or update should block startup.

Removing an ID disables it on the next managed start but leaves its Workshop
files cached. An empty `TMOD_MODS` leaves the existing cache and `enabled.json`
unchanged. `TMOD_AUTODOWNLOAD` and `TMOD_ENABLEDMODS` remain only for backward
compatibility.

## Password file

Environment variables are visible through Docker metadata. To keep the real
password out of that metadata, create `./secrets/tmod-password`, set:

```dotenv
TMOD_PASS=N/A
TMOD_PASS_FILE=/run/secrets/tmod-password
```

Then uncomment this mount in `docker-compose.yml`:

```yaml
- "./secrets/tmod-password:/run/secrets/tmod-password:ro"
```

Restrict access to the host file. `TMOD_PASS_FILE` applies to generated-config
mode; a custom server config is responsible for its own password handling.

## Custom server configuration

To use a native Terraria/tModLoader server configuration:

1. Create `customconfig.txt` beside `docker-compose.yml`.
2. Set `TMOD_USECONFIGFILE=Yes` in `.env`.
3. Uncomment the `customconfig.txt` volume in `docker-compose.yml`.
4. Keep `TMOD_PORT` equal to the `port` value in the custom file so Docker's
   port mapping and healthcheck target the correct listener.

The generated-server variables are ignored in this mode. `TMOD_MODS`, Workshop
policies, autosave, shutdown behavior, persistent paths, and health monitoring
remain container features and continue to apply.

## Server operations

### Console commands: use `inject`

The supported way to administer the running server is the image's `inject`
helper. Do not use `docker attach` for console commands: attach cannot replay a
configurable number of prior lines and can forward terminal signals to the
server process.

Use two terminals. In the first, show the last 100 filtered console lines and
continue following new output:

```bash
docker compose logs --tail=100 --follow tmodloader
```

Replace `100` with the history length you want. `Ctrl+C` stops only the log
viewer; it does not stop the container.

In the second terminal, send one console command at a time:

```bash
docker exec --user tml:tml tmodloader inject "help"
docker exec --user tml:tml tmodloader inject "playing"
docker exec --user tml:tml tmodloader inject "say Server restart in 10 minutes"
docker exec --user tml:tml tmodloader inject "save"
```

The Compose-native equivalent is:

```bash
docker compose exec --user tml:tml -T tmodloader inject "save"
```

`inject` verifies that the supervised server process is running, rejects empty
or multiline input, and writes the command through the private console FIFO.
No interactive TTY or `stdin_open` Compose setting is required.

For the unfiltered upstream console, follow the persistent raw log instead:

```bash
docker exec --user tml:tml tmodloader tail -n 100 -F /data/tModLoader/Logs/container-console.log
```

### Console log levels

`TMOD_LOG_LEVEL` controls only the stream shown by `docker logs`:

- `normal` keeps server, mod-loading, player, warning, and error messages, but
  collapses world generation to one line per stage and hides low-value launcher
  checks and the full launch command.
- `quiet` keeps server lifecycle, save, warning, error, exception, and crash
  messages.
- `debug` prints the complete unfiltered console stream.

The setting never discards diagnostics. The full current launch is written to
`./data/tModLoader/Logs/container-console.log`; the prior launch is retained as
`container-console.previous.log`, and tModLoader's native `server.log` remains
unchanged. If the server exits non-zero in `quiet` or `normal`, the container
automatically replays the final `TMOD_CRASH_LOG_LINES` raw lines to Docker logs.

Stop gracefully:

```bash
docker compose stop
```

The entrypoint announces the configured shutdown message, asks tModLoader to
exit, waits up to `TMOD_SHUTDOWN_TIMEOUT`, and preserves the server's exit
status during ordinary operation.

Logs and crash information are stored in `./data/tModLoader/Logs`. Docker marks
the container healthy after the supervised server PID exists, the current server log
reports `Server started`, and the internal TCP port accepts a connection. The
ten-minute health start period prevents slow first-time world generation from
being treated as an immediate failure; a successful check can report healthy
earlier.

## Updating and pinning images

Update the Compose deployment with:

```bash
docker compose pull
docker compose up -d
```

The supplied Compose file uses `pull_policy: always`, but an already-created
container is not replaced merely because a registry tag moved. Running `up -d`
after `pull` performs that replacement while retaining `./data`.

The container and tModLoader are versioned independently. `VERSION` is the
container's SemVer core. The bundled tModLoader version and channel are added to
each exact release:

| Purpose | Example | Behavior |
| --- | --- | --- |
| GitHub Release tag | `1.0.0+tml.v2026.07.3.0.stable` | Strict SemVer using build metadata for the bundled dependency. |
| Exact Docker tag | `1.0.0-tml-v2026-07-3-0-stable` | Docker-safe SemVer spelling; release workflows refuse to reuse it. |
| tModLoader lookup | `tml-v2026.07.3.0-stable` | Moves when that tModLoader release receives a newer container build. |
| Stable channel | `latest` or `stable` | Newest verified stable combination. |
| Preview channel | `preview` | Newest verified preview combination. |
| Compatibility | `v2026.07.3.0` | Legacy upstream-only alias retained during migration. |

Docker registries do not accept `+` in a tag, so the exact Docker form uses one
hyphenated prerelease identifier. The terminal `stable` or `preview` text is the
actual channel; the hyphen is a registry-safe representation of dependency
metadata rather than a statement that every Docker image is unstable.

Each exact combination also receives a GitHub Release containing its container
changelog, tModLoader release link, published tags, tested digest, and validation
summary. Use the digest shown in that release when the complete image must be
immutable:

```yaml
image: ghcr.io/crosis47/tmodloader@sha256:replace-with-reviewed-digest
```

## Built-in administration page (opt-in)

The private dashboard runs inside the game container on port 8080. It shows
server readiness, persistent backup success/failure status, archive sizes,
free-space warnings, and checksum verification. It can request cold backups,
stage configuration/mod changes, and apply them with a confirmed game restart.
No Docker socket is required. The interface is disabled by default.

Readiness checks observe the server process, startup log, and listening socket
without opening game connections or taking player slots. They do not simulate
a complete player login or verify world playability.

### Enable private access

1. Uncomment the loopback-only dashboard port mapping in `docker-compose.yml`.
   Set `TMOD_WEB_ENABLED=1` and `TMOD_WEB_ORIGIN=http://localhost:8080` in `.env`.
   Leave `TMOD_WEB_TOKEN_FILE` empty to use `/data/admin/token.argon2`.
2. Start with `docker compose up -d` and read `docker compose logs tmodloader`.
   Without a hash, only the setup interface starts; mod downloads and the game
   wait. The logs show a random one-time setup code.
3. Open `http://localhost:8080`. Enter the setup code, choose a unique 8–256
   character ASCII admin token without whitespace, and confirm it. Keep the
   token in your password manager. The server atomically saves only a salted
   Argon2id hash (0600 permissions) in the persistent data volume and resumes
   startup automatically. Sign in with the original token, not the hash.

Setup requires the configured Host/Origin and the one-time code; the code expires
when setup completes or the container restarts. Remote first-run setup requires
an HTTPS origin or a localhost SSH tunnel. Terminate HTTPS at your trusted reverse
proxy and keep the backend private. Treat access to container logs as privileged.
The token stays in browser tab memory after sign-in, not browser storage or cookies.

Upgrading to container 2.0.0: existing plaintext admin secret files are no longer accepted. Remove the old
plaintext mount and leave `TMOD_WEB_TOKEN_FILE` empty to provision through the UI,
or mount a pre-created Argon2id hash at the path in `TMOD_WEB_TOKEN_FILE`. Missing
hashes enter setup; malformed or unsupported hashes fail startup. Read-only secret
mounts must be provisioned externally before starting. The image includes the
`argon2` CLI and Python library. An interactive helper is also included:

```bash
docker compose exec --user tml tmodloader python3 /terraria-server/admin_auth.py setup
```

Use this helper to rotate credentials, then restart the container. To create an
external hash, use `setup --file /writable/path/token.argon2` in a container with
that directory mounted, then mount the resulting file read-only. The helper asks
for the token without echoing it and uses Argon2id v19, 64 MiB, 3 iterations, and
4 lanes. External hashes must use Argon2id v19, 19–256 MiB, 2–10 iterations,
1–8 lanes, and at least 16-byte salts and outputs. Plaintext is never migrated
automatically. Setup gating applies only when `TMOD_WEB_ENABLED=1`.

For a remote Docker host, use an SSH tunnel (for example,
`ssh -L 8080:127.0.0.1:8080 your-server`) or an authenticated HTTPS reverse proxy.
Do not publish the HTTP port directly to the internet or send the token over
unencrypted remote HTTP. For a reverse proxy, set `TMOD_WEB_ORIGIN` to the exact
external HTTPS origin, preserve its Host header, and forward to container port
8080 over a private network. CORS is not enabled. Requests with another Host or
Origin are rejected. No proxy-provided identity headers grant access.

### Environment mode versus web-managed mode

`TMOD_CONFIG_SOURCE=env` keeps settings read-only and preserves existing Compose
behavior. Backup and verification controls remain available. To allow edits,
set `TMOD_CONFIG_SOURCE=web` and recreate the container. Web mode cannot be
combined with `TMOD_USECONFIGFILE=Yes`.

In web mode, environment values provide the initial defaults. Saved overrides
live in `/data/admin/settings.json` and take precedence on subsequent starts.
Drafts live in `/data/admin/pending.json`. Both are included in data backups.
Saving a draft never changes the running game. **Review & apply** shows the
saved changes and requires confirmation before disconnecting players, stopping
the game, preparing configuration/mods, and restarting it. Unsubmitted form
edits are not applied. A failed mod update or startup leaves the game stopped
and the dashboard available: correct the draft and apply again. Check logs for
the detailed cause. This is not automated image rollback.

Docker ports/mounts, admin/Steam credentials, the game password, and configuration
mode remain Compose-managed. Password values are never returned by the API.
In web-managed mode, first boot saves editable Compose values as initial web
defaults. Saved web values override Compose on later boots, including empty
values. Compose supplies defaults only for newly introduced or absent fields.
World creation settings do not rewrite an existing world. When switching back
to `env`, saved web overrides are ignored, not deleted.

#### Create a world with a chosen evil

For the initial world, set `TMOD_WORLDEVIL=crimson` (or `corruption`) and
`TMOD_WORLDNAME=MyNewWorld` in `.env`, then start with `docker compose up -d`.
The name must not already have a matching `.wld` file. `random` preserves the
existing automatic creation behavior. This applies to generated configuration
(`TMOD_USECONFIGFILE=No`); mounted custom configurations remain operator-managed.

In the WebUI with `TMOD_CONFIG_SOURCE=web`, open **World configuration**, choose
**New world evil**, and enter an **unused World name**. Stage the settings and
apply changes. Apply saves and stops the current game, disconnects players,
generates the new world, and starts it. The old world is retained. Choosing an
existing name loads that world without changing its evil. Changing only the evil
setting does not convert or regenerate the current world.

Explicit evil creation accepts names up to 26 characters and seeds up to 39
characters, matching the dedicated server menu. The selected mods are loaded
before generation. Special seeds and mods can alter generation or include both
evils. Generation progress is recorded in the normal console log. Apply waits
up to ten minutes for generation and startup; very large modded worlds may exceed
that limit. Failed creation stops startup and reports the error.

For the bundled Terraria 1.4.4 tModLoader server, the evil menu is **1 Random, 2 Corruption, 3 Crimson**, and the
world-name prompt is followed by a seed prompt. After generation and saving, it
returns to world selection, not directly to “Server started”. Our helper waits
for that return and a nonempty world file before ending the creation process
and starting the configured server. It uses a temporary English-language config
for predictable prompts; the game server retains the selected language.

The [upstream server configuration example](https://github.com/tModLoader/tModLoader/blob/v2026.07.3.0/patches/tModLoader/Terraria/release_extras/serverconfig.txt)
documents `world`, `autocreate`, and `seed`, but no evil configuration key.
The [dedicated-server flow](https://github.com/tModLoader/tModLoader/blob/v2026.07.3.0/patches/tModLoader/Terraria/Main.cs.patch)
uses the startup world-selection menu. A running game does not switch worlds
through this menu; the WebUI's existing stop/start process handles the transition.

### Browse and choose Workshop mods

Mods explicitly tagged `Client` are removed from `enabled.json` on startup and
settings apply, including client-only members of collections. Cached downloads
are preserved. Confirmed client-only IDs are also removed from saved web-managed
`TMOD_MODS` values and drafts; Compose files themselves are never rewritten.
Collection entries remain intact, with client-only members filtered from the
enabled list. The filter runs on each load.
The apply popup lists client-only mods removed while saving its draft or loading
mods, using installed mod names. The notice remains visible in the final result;
cached files are retained. A missing installed name is explicitly identified.
Unknown or conflicting classifications are not removed. Workshop cards label
client-only mods and prevent adding them, while allowing existing selections to
be removed. This uses publisher metadata, not a complete compatibility check.

In-page search and graphical browsing remain hidden and locked
until a readable, nonempty Steam API key file is configured. A setup notice
explains how to unlock them. URL/ID import and its preview results remain available
without a Steam API key (dashboard authentication is still required).
With a Steam Web API key stored in
`./secrets/steam-api-key`, uncomment its secret bind mount and set
`TMOD_WORKSHOP_KEY_FILE=/run/secrets/steam-api-key`. Recreate the container.
The key is used only server-side, not sent to your browser or the game process.

The browser supports keyword search, an optional exact tag, popular/newest/
updated sorting, and pagination. Results are restricted to tModLoader, with
short-lived caching to limit Steam requests. Steam availability, rate limits,
and API access can affect search; failures do not change the selected mods.
Adding/removing an item only changes the saved draft. Apply from Configuration
or use **Apply changes** on Workshop when ready. Both review the complete saved
draft and use the same restart/progress dialog. Collection entries use the
existing `collection:ID` mechanism.
Steam metadata is not proof of multiplayer compatibility, supported server
version, or complete dependencies. Review the mod's Workshop page before use.

### Interactive server console

Applying opens a blocking progress dialog with live stages (save/stop, write settings, update mods,
start game, and health check), elapsed time, and the final result. Progress updates
every two seconds during an apply; stages are not a percentage or time estimate.
The dashboard cannot be edited and Escape cannot dismiss the dialog while the
operation is running. A completion or failure result enables Return to dashboard.
Reconnecting during an apply reopens progress; connection errors keep controls
blocked while status checks retry. Closing the browser does not cancel the apply.

Choose **Browse full history** in the console to read the retained raw log from
the beginning in pages of up to 64 KiB. Beginning, Previous page, and Next page
let you navigate without loading a potentially large log into browser memory.
History view pauses live updates; **Return to live output** resumes the tail.
The run dropdown lists first-to-last output time ranges in your browser's local
timezone. New runs record the first received output in a companion `.first` file;
the log's last-write time supplies the end of the range. Older logs without a
recorded first time explicitly show "First output unknown".
Older runs are preserved under `/data/tModLoader/Logs/console-history` as the
current/previous logs rotate. They survive container recreation with the data
bind mount. No automatic history deletion is performed: monitor disk usage and
remove unwanted archived logs manually. Previously discarded logs cannot be
recovered. Log contents can contain private information.

Overview lists running mods by display name and version, using completed loading
records from the game server log—not staged IDs or downloaded files. This does
not require a Steam API key. Unhealthy servers or unavailable loading records are
shown as unconfirmed rather than implying that cached mods are running.

Choose **Interactive console** in the navigation or **Open console** on Overview.
Recent raw output refreshes every two seconds while that tab is visible (up to
200 lines / 64 KiB). Toggle **Follow output** to pause automatic scrolling.
Enter commands such as `help`, `playing`, `save`, or `say Hello everyone` and
select **Send command**. The up/down arrows recall the last 40 commands in this
tab; history is not saved to browser storage. Delivery acknowledgement is not
proof that the game accepted or completed a command: check subsequent output.

This uses the same `inject` channel as the CLI, not a Linux shell. It requires
admin authentication, rejects multiline/control-character commands, and blocks
commands while a backup or administration operation is active. Commands act
immediately even in environment-managed mode; they are not staged settings.
`exit` and `exit-nosave` require confirmation and may stop the entire container,
disconnecting the dashboard. Start it through Docker afterward if necessary.
Mod commands can also change or destroy game state; only trusted administrators
should have access. Logs and commands may contain private information.

Configuration is grouped into Server, World, Backups, Mods & Workshop,
Runtime & logs, and Journey permissions, with explanations and running values
beside each editable setting. Compose-only settings remain separate.

The admin API has no Linux shell endpoint, filesystem browser, uploads, archive
downloads, or online restore. Use the
documented offline restore workflow below for recovery. Anyone holding the
admin token can change the server's configuration and installed mods; treat
it as an administrative credential.

## Backups

Backups run **inside the container**, as its normal non-root user, using the
`./backups:/backups` bind mount included in the example Compose file. No Docker
socket, host Python, root job, or systemd timer is needed. Startup prepares the
backup mount alongside `/data`.
The tool refuses backup storage that is not a separate mount.

`TMOD_BACKUP_MIN_FREE_MB=1024` reserves a minimum of 1 GiB of free backup storage.
Preflight rejects low space before stopping the game; set a larger reserve for
large worlds/mod sets. This is a free-space threshold, not an exact prediction
of compressed archive size. Persistent activity and last-success timestamps are
stored under `/data/.tmod-control/backup-status.json`; the admin page exposes
them along with archive count/size and remaining disk space.

```bash
docker compose exec --user tml:tml -T tmodloader tmod-backup backup
docker compose exec --user tml:tml -T tmodloader tmod-backup verify --archive /backups/tmod-backup-TIMESTAMP-ID
```

Set `TMOD_BACKUP_INTERVAL=1440` in `.env` for a backup every 24 hours, then
recreate the container with `docker compose up -d`. The default `0` disables
scheduling; manual backups still work. `TMOD_BACKUP_KEEP=7` retains seven
verified backups for this data directory. Intervals restart when the container
starts or a manual backup completes; this is not a wall-clock cron schedule and
missed runs are not replayed. Scheduled runs wait for a healthy server.

Backups **disconnect players**: the supervisor sends `exit` to save and stop the
game, archives worlds, mod configuration, Workshop state, and logs, validates
the archive and SHA-256 checksum, then restarts the game and checks health.
The container stays running. Health probes can report unhealthy during this
maintenance window; configure external auto-heal tools not to restart it then.
An unclean stop prevents archiving. Backup failures attempt to restart the game
and are reported in container logs and the manual command's exit status.
Retention runs only after backup and restart validation succeed. Incomplete,
invalid, and unrelated bundles are left alone. Monitor `[BACKUP]` messages with
`docker compose logs --tail=100 --follow tmodloader`.

The archive does not include `.env`, custom configuration mounted outside
`/data`, or password files. Back those up separately in protected storage.
Backups record a fingerprint of the bundled server and backup/runtime scripts,
not the Docker image digest (which is unavailable without daemon access).
Keep the original image digest separately for recovery. Backups and logs may
still contain private server data.
Checksums detect corruption, not malicious modifications: restore only trusted
archives. Allow disk space for the archive, extracted data, and original data.
Restored files belong to the container runtime user and retain traditional
permission bits; arbitrary ownership, filesystem ACLs, extended attributes,
links, nested mounts, special files, and sparse-file layout are not supported. Deployments
that depend on those features should use their host backup system instead.

```bash
docker compose stop tmodloader
docker compose run --rm --no-deps --entrypoint tmod-backup tmodloader restore \
  --archive /backups/tmod-backup-TIMESTAMP-ID --confirm
# Only start after restore reports success:
docker compose start tmodloader
docker compose ps
docker compose logs --tail=100 tmodloader
```

Restore checks the build fingerprint and validates/extracts the archive before
replacing data. A filesystem lock rejects restore while this image's server is
running. Use local storage with working POSIX locks; do not use network shares
or let other tools write to the same data. Image rollback remains a separate feature.

Original files are retained in `/data/.tmod-control/before-restore-*`, never
pruned automatically. This reserved control/recovery directory is excluded from
archives. Restore requires space for both original and restored data. The server
stays stopped until you start it and verify health; a restore success alone does
not prove the world is playable.

If restore is interrupted, `/data/.tmod-control/restore-pending` blocks startup.
Keep the container stopped, inspect that file for the original-data location,
and preserve both the current data and originals before manual recovery. Moves
occur per top-level entry, so an interrupted move can leave originals in both
locations. Only remove the marker after recovering a complete data set. Do not
delete or replace `server.lock`; its kernel lock is released automatically when
the processes exit. Remove retained originals manually only after validating
recovery and keeping an independent backup.

The complete persistent state is under `./data`. For a consistent cold backup,
stop the container, copy that directory to protected storage, and start the
container again:

```bash
docker compose stop
# Back up ./data with the host backup tool of your choice.
docker compose start
```

At minimum, protect `data/tModLoader/Worlds`, `ModConfigs`, and the Workshop/mod
state needed by the deployment. Test restoration rather than assuming a copied
backup is usable.

## Troubleshooting

### Container remains unhealthy

```bash
docker compose ps
docker compose logs --tail=200 tmodloader
docker inspect --format '{{json .State.Health}}' tmodloader
```

Confirm that world generation has finished, `TMOD_PORT` matches any custom
configuration, and the process has enough memory. Docker health status is
diagnostic; Compose's `restart: unless-stopped` does not restart a process solely
because its health result is `unhealthy`.

### Players cannot connect

Confirm `TMOD_HOST_PORT`, the host firewall rule, router forwarding if needed,
and the address players use. `docker compose config` should show the expected
published host port and internal target port.

### Workshop startup fails

Read the startup log for the specific missing or outdated Workshop ID. The
default offline policy permits cached startup only when all requested content
is present. A first-time download therefore requires Steam access. Private,
removed, or non-tModLoader collection items are excluded.

### Configuration is rejected

The fatal message names the invalid variable and range. Correct `.env`, run
`docker compose config`, and recreate the container with `docker compose up -d`.
Existing worlds are not regenerated merely because world-generation variables
change.

### Persistent directory is not writable

The initializer first tries to repair `/data` and `/backups`, then the
low-privilege entrypoint verifies access. A fatal message includes the runtime
UID/GID, failing path, owner/group, and numeric mode. Check for a read-only
mount, a filesystem that rejects Linux ownership changes, or a deployment that
removed the initializer's `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID`, or
`SETUID` capability. The supplied Compose file includes only those capabilities.

## Image automation

The publisher checks official tModLoader releases daily and can also build an
exact release on demand. It combines the repository's container `VERSION` with
the discovered tModLoader version, builds an untagged candidate digest, runs
Bash and configuration tests, starts and stops a real dedicated server, and
only then assigns the public GHCR tags and creates the corresponding GitHub
Release. Release notes are rendered from the matching version section in
`CHANGELOG.md` and include the exact tested digest. A failed candidate cannot
move a public tag or create a release.

Images are published to GitHub Container Registry. Docker Hub credentials are
not required for this repository's release workflow.

## Credits

- [Terraria](https://terraria.org/) and
  [its Steam page](https://store.steampowered.com/app/105600/Terraria/)
- [tModLoader](https://www.tmodloader.net/),
  [its source](https://github.com/tModLoader/tModLoader), and
  [its Steam page](https://store.steampowered.com/app/1281930/tModLoader/)
- [JACOBSMILE/tmodloader1.4](https://github.com/JACOBSMILE/tmodloader1.4),
  the original project on which this hard fork is based
- [ldericher/tmodloader-docker](https://github.com/ldericher/tmodloader-docker)
  for the Terraria 1.3 implementation and console-injection approach
- [rfvgyhn/tmodloader-docker](https://github.com/rfvgyhn/tmodloader-docker)
- [guillheu/tmodloader-docker](https://github.com/guillheu/tmodloader-docker)
- [FlorentLM/tmodloader1.4](https://github.com/FlorentLM/tmodloader1.4)

The repository's container code and scripts are distributed under
[LICENSE.md](LICENSE.md). Terraria, tModLoader, SteamCMD, and their respective
assets remain the property of their owners.
