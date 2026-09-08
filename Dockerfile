# syntax=docker/dockerfile:1

# The Steam client is still 32-bit, so use its Ubuntu image as the source for
# steamcmd and the i386 libraries it needs.
FROM steamcmd/steamcmd:ubuntu-22 AS builder

# Install prerequisites to download steamcmd
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /root/installer

# Download and unpack installer
RUN curl --fail --silent --show-error --location \
        https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar --extract --gzip --verbose

# Pin the runtime distribution. Tracking ubuntu:latest allowed Ubuntu 26.04 to
# land without its matching .NET native dependencies and broke every new image.
FROM ubuntu:24.04

# The TMOD Version. Ensure that you follow the correct format. Version releases can be found at https://github.com/tModLoader/tModLoader/releases if you're lost.
ARG TMOD_VERSION=v2026.07.3.0

# Published images use an unprivileged runtime identity. Custom local builds can
# select another fixed identity to match an existing host-owned data directory.
ARG TMOD_UID=1000
ARG TMOD_GID=1000

# The shutdown message is broadcast to the game chat when the container was stopped from the host.
ENV TMOD_SHUTDOWN_MESSAGE="Server is shutting down NOW!"
ENV TMOD_SHUTDOWN_TIMEOUT="90"

# The autosave feature will save the world periodically. The interval is in minutes.
ENV TMOD_AUTOSAVE_INTERVAL="10"

# Docker console verbosity. Complete raw output remains in the persistent log.
ENV TMOD_LOG_LEVEL="normal"
ENV TMOD_CRASH_LOG_LINES="200"

# Workshop mods to keep current and enable when the server starts.
# Example format: 2824688072,2824688266,2835214226
ENV TMOD_MODS=""

# Deprecated compatibility variables. TMOD_MODS takes precedence when non-empty.
ENV TMOD_AUTODOWNLOAD=""
ENV TMOD_ENABLEDMODS=""

# Retry transient Steam Workshop failures before aborting startup.
ENV TMOD_DOWNLOAD_RETRIES="3"
ENV TMOD_DOWNLOAD_RETRY_DELAY="10"
ENV TMOD_MOD_OFFLINE_POLICY="use-cache"
ENV TMOD_COLLECTION_MAX_ITEMS="1000"

# If you want to specify your own config, set the following to "Yes".
ENV TMOD_USECONFIGFILE="No"
ENV TMOD_PASS_FILE=""

#--------- CONFIG SECTION --------- #
# The following environment variables will configure common settings for the tModLoader server.

# motd
ENV TMOD_MOTD="A tModLoader server powered by Docker!"
# password
ENV TMOD_PASS="docker"
# maxplayers
ENV TMOD_MAXPLAYERS="8"
# worldname
ENV TMOD_WORLDNAME="Docker"
# autocreate
ENV TMOD_WORLDSIZE="3"
# seed
ENV TMOD_WORLDSEED="Docker"
# difficulty
ENV TMOD_DIFFICULTY="1"
# secure
ENV TMOD_SECURE="0"
# language
ENV TMOD_LANGUAGE="en-US"
# npcstream
ENV TMOD_NPCSTREAM="60"
# upnp
ENV TMOD_UPNP="0"
# priority
ENV TMOD_PRIORITY="1"
# port
ENV TMOD_PORT="7777"

# JOURNEY MODE POWER PERMISSIONS

# journeypermission_time_setfrozen
ENV TMOD_JOURNEY_SETFROZEN="0"
# journeypermission_time_setdawn
ENV TMOD_JOURNEY_SETDAWN="0"
# journeypermission_time_setnoon
ENV TMOD_JOURNEY_SETNOON="0"
# journeypermission_time_setdusk
ENV TMOD_JOURNEY_SETDUSK="0"
# journeypermission_time_setmidnight
ENV TMOD_JOURNEY_SETMIDNIGHT="0"
# journeypermission_godmode
ENV TMOD_JOURNEY_GODMODE="0"
# journeypermission_wind_setstrength
ENV TMOD_JOURNEY_WIND_STRENGTH="0"
# journeypermission_rain_setstrength
ENV TMOD_JOURNEY_RAIN_STRENGTH="0"
# journeypermission_time_setspeed
ENV TMOD_JOURNEY_TIME_SPEED="0"
# journeypermission_rain_setfrozen
ENV TMOD_JOURNEY_RAIN_FROZEN="0"
# journeypermission_wind_setfrozen
ENV TMOD_JOURNEY_WIND_FROZEN="0"
# journeypermission_increaseplacementrange
ENV TMOD_JOURNEY_PLACEMENT_RANGE="0"
# journeypermission_setdifficulty
ENV TMOD_JOURNEY_SET_DIFFICULTY="0"
# journeypermission_biomespread_setfrozen
ENV TMOD_JOURNEY_BIOME_SPREAD="0"
# journeypermission_setspawnrate
ENV TMOD_JOURNEY_SPAWN_RATE="0"

# Loading a custom configuration file expects a Terraria server config mounted
# at /terraria-server/customconfig.txt. Set this to "Yes" to use that file.
# ENV TMOD_USECONFIGFILE="No"


# Copy steamcmd and its required libs from the builder
COPY --from=builder /root/installer/steamcmd.sh /usr/lib/games/steam/
COPY --from=builder /root/installer/linux32/steamcmd /usr/lib/games/steam/
COPY --from=builder /usr/games/steamcmd /usr/bin/steamcmd
COPY --from=builder /lib/i386-linux-gnu /lib/
COPY --from=builder /root/installer/linux32/libstdc++.so.6 /lib/
RUN chown -R root:root /usr/bin/ /lib/ /usr/lib/
RUN chmod 755 \
        /usr/bin/steamcmd \
        /usr/lib/games/steam/steamcmd \
        /usr/lib/games/steam/steamcmd.sh

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        jq \
        libc6 \
        libgcc-s1 \
        libgssapi-krb5-2 \
        libicu74 \
        libsdl2-2.0-0 \
        libssl3 \
        libstdc++6 \
        locales \
        tini \
        tzdata \
        unzip \
        util-linux \
        wget \
        zlib1g \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG="en_US.UTF-8"
ENV LC_ALL="en_US.UTF-8"

RUN case "$TMOD_UID" in ''|*[!0-9]*|0) echo "TMOD_UID must be a positive integer." >&2; exit 1 ;; esac \
    && case "$TMOD_GID" in ''|*[!0-9]*|0) echo "TMOD_GID must be a positive integer." >&2; exit 1 ;; esac \
    && existing_user="$(getent passwd "$TMOD_UID" | cut -d: -f1)" \
    && existing_group="$(getent group "$TMOD_GID" | cut -d: -f1)" \
    && if [ "$existing_user" = ubuntu ] && [ "$existing_group" = ubuntu ]; then \
        groupmod --new-name tml ubuntu; \
        usermod --login tml --comment 'tModLoader runtime' --home /home/tml --move-home ubuntu; \
    elif [ -n "$existing_user" ] || [ -n "$existing_group" ]; then \
        echo "TMOD_UID or TMOD_GID is already assigned in the base image." >&2; \
        exit 1; \
    else \
        groupadd --gid "$TMOD_GID" tml; \
        useradd --no-log-init --uid "$TMOD_UID" --gid "$TMOD_GID" \
            --create-home --home-dir /home/tml --shell /bin/bash tml; \
    fi \
    && install -d -m 0755 -o tml -g tml \
        /home/tml/.steam \
        /data \
        /data/steamMods \
        /data/tModLoader \
        /data/tModLoader/Logs \
        /data/tModLoader/ModConfigs \
        /data/tModLoader/Mods \
        /data/tModLoader/Worlds \
        /terraria-server

ENV HOME="/home/tml"
ENV USER="tml"

USER tml:tml

EXPOSE 7777

WORKDIR /terraria-server

RUN steamcmd /terraria-server +login anonymous +quit

RUN curl --fail --silent --show-error --location \
        --retry 5 --retry-delay 5 --retry-max-time 120 --retry-all-errors \
        --output tModLoader.zip \
        "https://github.com/tModLoader/tModLoader/releases/download/${TMOD_VERSION}/tModLoader.zip" \
    && unzip -o tModLoader.zip \
    && rm tModLoader.zip

COPY --chown=tml:tml entrypoint.sh .
COPY --chown=tml:tml run-server.sh .
COPY --chown=tml:tml log-filter.sh .
COPY --chown=tml:tml manage-mods.sh .
COPY --chown=tml:tml inject.sh /usr/local/bin/inject
COPY --chown=tml:tml healthcheck.sh /usr/local/bin/healthcheck
COPY --chown=tml:tml autosave.sh .
COPY --chown=tml:tml prepare-config.sh .

RUN find ./LaunchUtils -type f -name '*.sh' -exec chmod 755 {} + \
    && chmod 755 ./entrypoint.sh \
    && chmod 755 ./run-server.sh \
    && chmod 755 ./log-filter.sh \
    && chmod 755 ./manage-mods.sh \
    && chmod 755 ./autosave.sh \
    && chmod 755 /usr/local/bin/healthcheck \
    && chmod 755 /usr/local/bin/inject \
    && chmod 755 ./prepare-config.sh \
    && chmod 755 ./start-tModLoaderServer.sh

RUN bash -c 'set -Eeo pipefail; \
        cd ./LaunchUtils; \
        . ./BashUtils.sh; \
        LogFile=/tmp/dotnet-install.log; \
        . ./DotNetVersion.sh; \
        run_script ./InstallDotNet.sh' \
    && test -x ./dotnet/dotnet \
    && ./dotnet/dotnet --info \
    && rm -rf ./tModLoader-Logs \
    && ln -s /data/tModLoader/Logs ./tModLoader-Logs

HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 CMD ["healthcheck"]

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]
