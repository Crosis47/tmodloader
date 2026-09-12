#!/usr/bin/env bash
# Launch the AMD64 image's x86 SteamCMD with isolated libraries.
set -Eeuo pipefail

steam_root="$HOME/.local/share/steamcmd"
mkdir -p "$steam_root"
if [[ ! -x "$steam_root/linux32/steamcmd" ]]; then
    cp -a /opt/steamcmd-seed/. "$steam_root/"
fi
libraries="$steam_root/linux32:/opt/steam-runtime/lib"
cd "$steam_root"
launcher=(env "LD_LIBRARY_PATH=$libraries")

# Valve uses status 42 to request a restart after updating its executable.
# Relaunch the updated binary with the same arguments and library path.
ulimit -n 2048
while true; do
    status=0
    "${launcher[@]}" "$steam_root/linux32/steamcmd" "$@" || status=$?
    if [[ "$status" != 42 ]]; then
        exit "$status"
    fi
done
