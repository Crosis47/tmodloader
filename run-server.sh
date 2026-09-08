#!/usr/bin/env bash

set -o pipefail

config_path="$1"
output_pipe="$2"
status_path="$3"

/terraria-server/LaunchUtils/ScriptCaller.sh \
    -server \
    -tmlsavedirectory /data/tModLoader \
    -steamworkshopfolder /data/steamMods/steamapps/workshop \
    -config "$config_path" \
    2>&1 | tee "$output_pipe"
server_status=${PIPESTATUS[0]}
printf '%s\n' "$server_status" > "$status_path"
exit "$server_status"
