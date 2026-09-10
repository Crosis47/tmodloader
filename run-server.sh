#!/usr/bin/env bash

set -Eeuo pipefail

config_path="$1"
log_level="${TMOD_LOG_LEVEL:-normal}"
crash_log_lines="${TMOD_CRASH_LOG_LINES:-200}"
log_dir="${TMOD_LOG_DIR:-/data/tModLoader/Logs}"
script_caller="${TMOD_SCRIPT_CALLER:-/terraria-server/LaunchUtils/ScriptCaller.sh}"
log_filter="${TMOD_LOG_FILTER:-/terraria-server/log-filter.sh}"
raw_log="$log_dir/container-console.log"
previous_log="$log_dir/container-console.previous.log"

mkdir -p "$log_dir"
umask 077
if [[ -f "$raw_log" ]]; then
    if [[ -f "$previous_log" ]]; then
        mkdir -p "$log_dir/console-history"
        archive="$(mktemp "$log_dir/console-history/run-$(date -u -r "$previous_log" +%Y%m%dT%H%M%SZ)-XXXXXX.log")"
        mv -- "$previous_log" "$archive"
        if [[ -f "$previous_log.first" ]]; then mv -- "$previous_log.first" "$archive.first"; fi
    fi
    mv -f "$raw_log" "$previous_log"
    rm -f "$previous_log.first"
    if [[ -f "$raw_log.first" ]]; then mv -- "$raw_log.first" "$previous_log.first"; fi
fi
umask 077
: > "$raw_log"
rm -f "$raw_log.first"

set +e
bash "$script_caller" \
    -server \
    -tmlsavedirectory /data/tModLoader \
    -steamworkshopfolder /data/steamMods/steamapps/workshop \
    -config "$config_path" \
    2>&1 | python3 "$(dirname "${BASH_SOURCE[0]}")/console_tee.py" "$raw_log" | bash "$log_filter" "$log_level"
pipeline_status=("${PIPESTATUS[@]}")
set -e

server_status="${pipeline_status[0]}"
if [[ "$server_status" == "0" && ( "${pipeline_status[1]}" != "0" || "${pipeline_status[2]}" != "0" ) ]]; then
    server_status=70
    printf '[!!] The server console logging pipeline failed.\n' >&2
fi

if [[ "$server_status" != "0" && "$log_level" != "debug" && "$crash_log_lines" != "0" ]]; then
    printf '\n[!!] tModLoader failed; replaying the last %s raw console lines from %s\n' \
        "$crash_log_lines" "$raw_log" >&2
    tail -n "$crash_log_lines" "$raw_log" >&2
fi

exit "$server_status"
