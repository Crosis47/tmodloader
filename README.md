# tModLoader Powered By Docker
[![Publish](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-publish.yml?branch=master&logo=github&label=image%20publisher&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-publish.yml)
[![CI](https://img.shields.io/github/actions/workflow/status/Crosis47/tmodloader/docker-ci.yml?logo=github&label=docker%20CI&style=for-the-badge)](https://github.com/Crosis47/tmodloader/actions/workflows/docker-ci.yml)

---

[View on GitHub](https://github.com/Crosis47/tmodloader) |
[View container images](https://github.com/Crosis47/tmodloader/pkgs/container/tmodloader)

This Docker Image is designed to allow for easy configuration and setup of a modded Terraria server powered by tModLoader.

## Features
- Easy Downloading of tModLoader mods by Workshop ID
- Scheduled World Saving
- Graceful Shutdowns
- Configuration Files are optional
- GitHub automation that publishes stable and preview tModLoader releases
- Build-time .NET runtime checks to prevent broken images from being published
- Real server smoke tests before any public image tag is updated
- Docker health status and persistent tModLoader logs
- Recursive Steam Workshop collection expansion with offline cache fallback

## Credits & Mentions
- Terraria
  - [Website](https://terraria.org/)
  - [Steam Store Page](https://store.steampowered.com/app/105600/Terraria/)
- tModLoader
  - [Website](https://www.tmodloader.net/)
  - [Steam Store Page](https://store.steampowered.com/app/1281930/tModLoader/)
  - [Github](https://github.com/tModLoader/tModLoader)
- [ldericher](https://github.com/ldericher/tmodloader-docker)'s Docker implementation of tModLoader for Terraria 1.3 and command injection functionality
- [rfvgyhn](https://github.com/rfvgyhn/tmodloader-docker)'s Docker implementation of tModLoader for Terraria 1.3
- [guillheu](https://github.com/guillheu/tmodloader-docker)'s Docker implementation of tModLoader for Terraria 1.4
- [FlorentLM](https://github.com/FlorentLM/tmodloader1.4) For helping clean up the Dockerfile & resolving some security concerns.
- [JACOBSMILE/tmodloader1.4](https://github.com/JACOBSMILE/tmodloader1.4), the original project this maintained fork is based on

# Repository Automation & Daily Automated Builds

The publisher checks the official tModLoader releases every day. It publishes version-selecting tags plus two moving channels:

- `latest` is the newest stable tModLoader release.
- `preview` is the newest release when that release is a prerelease.
- `vYYYY.MM.X.Y` tags select one exact tModLoader release.

The publisher passes each release as a Docker build argument instead of rewriting the Dockerfile. It builds an untagged candidate, runs script tests and a real dedicated-server startup/shutdown test against that exact image digest, and only then moves the public tags. This prevents stable and preview jobs from repeatedly reverting each other's commits and keeps failed candidates away from normal pull commands.

A version tag identifies the tModLoader release but can move when this container receives a fix. Pin the displayed image digest as `image@sha256:...` when the complete container build must be immutable.

## To Pull the Latest tModLoader Image

```bash
# ":latest" is always the newest stable tModLoader release.
docker pull ghcr.io/crosis47/tmodloader:latest
```

## To Pull a Specific tModLoader Image Version
```bash
# Replace 'v2022.09.47.13' with the version string found at https://github.com/tModLoader/tModLoader/releases
docker pull ghcr.io/crosis47/tmodloader:v2022.09.47.13
```

# Container Preparation

### Data Directory
Create a directory on HOST machine to house persistent files.

```bash
# Making the Data directory
mkdir /path/to/data/directory
```

```bash
# The below line is a mapped volume for the Docker container.
-v /path/to/data/directory:/data
```

Within this directory, you will find the following file structure:
```
/data/
├─ steamMods/
│  ├─ steamapps/
│  │  ├─ workshop/
│  │  │  ├─ content/
│  │  │  │  ├─ 1281930/
├─ tModLoader/
│  ├─ ModConfigs/
│  ├─ Logs/
│  ├─ Mods/
│  │  ├─ collection-cache/
│  │  ├─ enabled.json
│  ├─ Worlds/
```

Steam Workshop content is stored within `steamMods`.

The server's Mod Configurations, Mod directory and World directories are stored within `tModLoader`.


## Managing Mods
Every Workshop item on Steam has a unique identifier which can be found by visiting the store page directly. For example, for the [Calamity Mod](https://steamcommunity.com/sharedfiles/filedetails/?id=2824688072), you can find the Workshop ID from the URL. In this case, **2824688072** is the ID. This Docker container is capable of downloading tModLoader mods directly from the Steam Workshop to streamline the setup process.

Set `TMOD_MODS` to one comma-separated list of the Workshop IDs the server should keep current **and** enable. Prefix a Steam Workshop collection ID with `collection:` to recursively include its valid tModLoader items:

```bash
-e TMOD_MODS=2824688072,collection:3443710509
```

On each start, the container compares the installed Workshop content manifest with Steam's current content manifest. SteamCMD runs only for missing or outdated items. Collections are filtered to public Workshop items for tModLoader application `1281930`, and their last successful expansion is cached under `/data/tModLoader/Mods/collection-cache`.

The default `TMOD_MOD_OFFLINE_POLICY=use-cache` keeps the server available during a Steam outage when every requested mod is already cached. Startup still fails if any requested mod is missing. Set the policy to `strict` if inability to verify or update any mod must block startup. The resolved `.tmod` names are written atomically to `/data/tModLoader/Mods/enabled.json`.

Removing an ID from `TMOD_MODS` disables it at the next start but leaves its Workshop files cached. If `TMOD_MODS` is empty, the container leaves the existing Workshop cache and `enabled.json` unchanged.

`TMOD_AUTODOWNLOAD` and `TMOD_ENABLEDMODS` remain available for compatibility with existing deployments, but they are deprecated. A non-empty `TMOD_MODS` value takes precedence over both.

# Environment Variables
The following are all of the environment variables that are supported by the container. These handle server functionality and Terraria server configurations.

| Variable      | Default Value | Description |
| ----------- | ----------- | ----------- |
| TMOD_SHUTDOWN_MESSAGE | Server is shutting down NOW! | The message which will be sent to the in-game chat upon container shutdown.
| TMOD_SHUTDOWN_TIMEOUT | 90 | Seconds to wait for a graceful server shutdown before terminating its tmux session.
| TMOD_AUTOSAVE_INTERVAL   | 10 | The autosave interval in minutes. Set to `0` to disable scheduled save commands.
| TMOD_MODS | N/A | Comma-separated Workshop Mod IDs and `collection:ID` entries to keep current and enable on startup.
| TMOD_DOWNLOAD_RETRIES | 3 | Number of SteamCMD download attempts before startup fails.
| TMOD_DOWNLOAD_RETRY_DELAY | 10 | Seconds to wait between SteamCMD download attempts.
| TMOD_MOD_OFFLINE_POLICY | use-cache | `use-cache` starts with complete cached mods during Steam failures; `strict` blocks startup.
| TMOD_COLLECTION_MAX_ITEMS | 1000 | Safety limit for recursively expanded collection items and nested collections.
| TMOD_AUTODOWNLOAD | N/A | Deprecated compatibility variable for IDs to download or update.
| TMOD_ENABLEDMODS | N/A | Deprecated compatibility variable for IDs to enable.
| TMOD_USECONFIGFILE | No | Set to `Yes` to use a file mounted at `/terraria-server/customconfig.txt` instead of generated environment-variable settings.
| TMOD_MOTD | A tModLoader server powered by Docker! | The Message of the Day which prints in the chat upon joining the server.
| TMOD_PASS | docker | The password players must supply to join the server. Set this variable to "N/A" to disable requiring a password on join. (Not Recommended)
| TMOD_PASS_FILE | N/A | Read the generated-config password from a mounted file. This overrides `TMOD_PASS` and keeps the value out of the server process environment.
| TMOD_MAXPLAYERS | 8 | The maximum number of players which can join the server at once.
| TMOD_WORLDNAME | Docker | The name of the world file. This is seen in-game as well as will be used for the name of the .WLD file.
| TMOD_WORLDSIZE | 3 | When generating a new world (and only when generating a new world), this variable will be used to designate the size. 1 = Small, 2 = Medium, 3 = Large
| TMOD_WORLDSEED | Docker | The seed for a new world.
| TMOD_DIFFICULTY | 1 | When generating a new world (and only when generating a new world), this variable will set the difficulty of the world. 0 = Normal, 1 = Expert, 2 = Master, 3 = Journey.
| TMOD_SECURE | 0 | Adds additional cheat protection.
| TMOD_LANGUAGE | en-US | Sets the language for the server. Available options are: `en-US` (English), `de-DE` (German), `it-IT` (Italian), `fr-FR` (French), `es-ES` (Spanish), `ru-RU` (Russian), `zh-Hans` (Chinese), `pt-BR` (Portuguese), `pl-PL` (Polish).
| TMOD_NPCSTREAM | 60 | Reduces enemy skipping, but increases bandwidth usage. The lower the number, the less skipping will happen, but more data is sent. 0 is off.
| TMOD_UPNP | 0 | Automatically forwards ports with uPNP (untested, and may not work in all cases depending on network configuration)
| TMOD_PORT | 7777 | Set the port for the tModLoader server to run on within the container.
| TMOD_PRIORITY | 1 | Process priority from 0 (Realtime) through 5 (Idle).

Generated settings are validated before tModLoader starts. Invalid ports, player counts, world sizes, difficulties, permission values, language-code formats, unsafe world names, and multiline config values fail with a specific message rather than producing a damaged configuration. Password values are redacted from startup output, the generated file is mode `0600`, and the password variables are removed before tModLoader writes its environment log.

For stronger secret handling, mount a password file read-only and set `TMOD_PASS_FILE`:

```bash
--mount type=bind,source=/path/to/server-password,target=/run/secrets/tmod-password,readonly \
-e TMOD_PASS_FILE=/run/secrets/tmod-password
```

The following are environment variables which control Journey Mode settings. For all of these settings, 
* 0 = Locked for everyone 
* 1 = Only Changeable by Host
* 2 = Can be changed by everyone. 

Refer to the [Terraria Server Wiki](https://terraria.fandom.com/wiki/Server) for more information. The default setting for all of these is 0 when not explicitly set.

* TMOD_JOURNEY_SETFROZEN
* TMOD_JOURNEY_SETDAWN
* TMOD_JOURNEY_SETNOON
* TMOD_JOURNEY_SETDUSK
* TMOD_JOURNEY_SETMIDNIGHT
* TMOD_JOURNEY_GODMODE
* TMOD_JOURNEY_WIND_STRENGTH
* TMOD_JOURNEY_RAIN_STRENGTH
* TMOD_JOURNEY_TIME_SPEED
* TMOD_JOURNEY_RAIN_FROZEN
* TMOD_JOURNEY_WIND_FROZEN
* TMOD_JOURNEY_PLACEMENT_RANGE
* TMOD_JOURNEY_SET_DIFFICULTY
* TMOD_JOURNEY_BIOME_SPREAD
* TMOD_JOURNEY_SPAWN_RATE

# Running the Container

## Docker Command

```bash
# Pull the image
docker pull ghcr.io/crosis47/tmodloader:latest

# Execute the container
docker run -p 7777:7777 --name tmodloader --rm \
  -v /path/to/data:/data \
  -e TMOD_SHUTDOWN_MESSAGE='Goodbye!' \
  -e TMOD_AUTOSAVE_INTERVAL='15' \
  -e TMOD_MODS='2824688072,collection:3443710509' \
  -e TMOD_MOTD='Welcome to my tModLoader Server!' \
  -e TMOD_PASS='secret' \
  -e TMOD_MAXPLAYERS='16' \
  -e TMOD_WORLDNAME='Earth' \
  -e TMOD_WORLDSIZE='2' \
  -e TMOD_WORLDSEED='not the bees!' \
  -e TMOD_DIFFICULTY='3' \
  ghcr.io/crosis47/tmodloader:latest
```

## Docker Compose

Included in the Github repository is a sample `docker-compose.yml` file. Copy `.env.example` to `.env` to set the host port, container port, and password without editing the Compose file. `TMOD_HOST_PORT` controls the host-facing port while `TMOD_PORT` controls the port on which tModLoader listens inside the container.

Once you are satisfied with the Compose file, pull and start it with the following commands.
```bash
docker compose pull
docker compose up -d
```

An image tag changing in a registry does not replace an already-created container. Run those commands again to update it. The included Compose file also uses `pull_policy: always`, so each `up` checks for a newer image.

## Health and Logs

Docker marks the container healthy only after the tmux server session exists, the current persistent `server.log` contains `Server started`, and the configured TCP port accepts a connection. World generation can take several minutes, so the image provides a ten-minute health start period.

```bash
docker inspect --format '{{.State.Health.Status}}' tmodloader
```

tModLoader logs, including archived logs and crash details, persist under `/data/tModLoader/Logs`. Replacing the container therefore no longer removes the diagnostic files.

# Interacting with the Server

To send commands to the server once it has started, use the following command on your Host machine. The below example will send "Hello World" to the game chat.

```bash
docker exec tmodloader inject "say Hello World!"
```
You can alternatively use the ID of the container in place of `tmodloader` if you did not name your configuration.

_Credit to [ldericher](https://github.com/ldericher/tmodloader-docker) for this method of command injection to tModLoader's console._

# Notes
I do not own tModLoader or Terraria. This Docker Image was created for players to easily host a game server with Docker, and is not intended to infringe on any Copyright, Trademark or Intellectual Property.
