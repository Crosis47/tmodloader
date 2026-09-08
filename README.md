# tModLoader Dedicated Server Container

[![Publish](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-publish.yml?branch=master&logo=github&label=image%20publisher&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-publish.yml)
[![CI](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-ci.yml?logo=github&label=docker%20CI&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-ci.yml)

[GitHub repository](https://github.com/Crosis47/tmodloader) |
[GHCR images](https://github.com/Crosis47/tmodloader/pkgs/container/tmodloader) |
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
- Docker health status based on the live server session, log, and TCP port.
- Validated environment-based server configuration or an optional custom file.
- Password redaction and file-based password support.
- Scheduled saves, console command injection, and graceful shutdown.

## Requirements

- Docker Engine with the Compose plugin, or Docker Desktop.
- Enough memory for the selected world and mod pack; requirements vary greatly
  between mod collections.
- A writable host directory for `/data`.
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

### 2. Configure the server

Open `.env` and, at minimum, review these values:

```dotenv
TMOD_HOST_PORT=7777
TMOD_PORT=7777
TMOD_MODS=
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
docker compose logs -f
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
| `TMOD_SHUTDOWN_TIMEOUT` | `90` | Seconds allowed for graceful shutdown before the tmux session is terminated. |
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

Follow the live console output:

```bash
docker compose logs -f tmodloader
```

Send a tModLoader console command:

```bash
docker exec tmodloader inject "say Hello World!"
```

Stop gracefully:

```bash
docker compose stop
```

The entrypoint announces the configured shutdown message, asks tModLoader to
exit, waits up to `TMOD_SHUTDOWN_TIMEOUT`, and preserves the server's exit
status during ordinary operation.

Logs and crash information are stored in `./data/tModLoader/Logs`. Docker marks
the container healthy after the tmux session exists, the current server log
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

Available tags:

- `latest`: newest supported stable tModLoader release.
- `preview`: newest prerelease when stable and prerelease differ.
- `vYYYY.MM.X.Y`: a specific upstream tModLoader release.

A version tag can be rebuilt when this container receives a fix. Use the digest
shown by GHCR when the complete image must be immutable:

```yaml
image: ghcr.io/crosis47/tmodloader@sha256:replace-with-reviewed-digest
```

## Backups

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

## Image automation

The publisher checks official tModLoader releases daily and can also build an
exact release on demand. It builds an untagged candidate digest, runs Bash and
configuration tests, starts and stops a real dedicated server, and only then
assigns the public GHCR version and channel tags. A failed candidate cannot move
`latest`, `preview`, or a version tag.

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
