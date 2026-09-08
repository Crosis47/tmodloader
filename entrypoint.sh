#!/usr/bin/env bash

set -Eeuo pipefail

pipe="/tmp/tmod.pipe"
status_path="/tmp/tmod.exit"
generated_config_path="/terraria-server/serverconfig.txt"
custom_config_path="/terraria-server/customconfig.txt"
config_path="$generated_config_path"
autosave_pid=""
cat_pid=""

fail() {
    printf '[!!] FATAL: %s\n' "$*" >&2
    exit 1
}

reject_line_breaks() {
    local variable_name="$1"
    local value="$2"

    if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
        fail "$variable_name cannot contain line breaks."
    fi
}

use_custom_config() {
    case "${TMOD_USECONFIGFILE,,}" in
        yes|true|1) return 0 ;;
        no|false|0) return 1 ;;
        *) fail "TMOD_USECONFIGFILE must be Yes/No, true/false, or 1/0." ;;
    esac
}

load_password_file() {
    if [[ -z "${TMOD_PASS_FILE:-}" ]]; then
        return
    fi
    [[ -r "$TMOD_PASS_FILE" ]] || fail "TMOD_PASS_FILE is not readable: $TMOD_PASS_FILE"
    TMOD_PASS="$(<"$TMOD_PASS_FILE")"
    export TMOD_PASS
}

stop_autosave() {
    if [[ -n "$autosave_pid" ]] && kill -0 "$autosave_pid" 2>/dev/null; then
        kill "$autosave_pid" 2>/dev/null || true
        wait "$autosave_pid" 2>/dev/null || true
    fi
}

shutdown() {
    local deadline

    trap - TERM INT
    stop_autosave
    if tmux has-session -t tmodloader 2>/dev/null; then
        inject "say $TMOD_SHUTDOWN_MESSAGE" || true
        sleep 3
        inject "exit" || true
        deadline=$((SECONDS + ${TMOD_SHUTDOWN_TIMEOUT:-90}))
        while tmux has-session -t tmodloader 2>/dev/null; do
            if ((SECONDS >= deadline)); then
                printf '[!!] Graceful shutdown timed out; terminating the server session.\n' >&2
                tmux kill-session -t tmodloader 2>/dev/null || true
                break
            fi
            sleep 1
        done
    fi

    [[ -z "$cat_pid" ]] || wait "$cat_pid" 2>/dev/null || true
    rm -f "$pipe" "$status_path"
    exit 0
}

reject_line_breaks TMOD_SHUTDOWN_MESSAGE "$TMOD_SHUTDOWN_MESSAGE"
[[ "${TMOD_AUTOSAVE_INTERVAL:-}" =~ ^[0-9]+$ ]] || fail "TMOD_AUTOSAVE_INTERVAL must be a non-negative integer."
[[ "${TMOD_SHUTDOWN_TIMEOUT:-90}" =~ ^[1-9][0-9]*$ ]] || fail "TMOD_SHUTDOWN_TIMEOUT must be a positive integer."
TMOD_LOG_LEVEL="${TMOD_LOG_LEVEL:-normal}"
TMOD_LOG_LEVEL="${TMOD_LOG_LEVEL,,}"
case "$TMOD_LOG_LEVEL" in
    quiet|normal|debug) ;;
    *) fail "TMOD_LOG_LEVEL must be quiet, normal, or debug." ;;
esac
TMOD_CRASH_LOG_LINES="${TMOD_CRASH_LOG_LINES:-200}"
[[ "$TMOD_CRASH_LOG_LINES" =~ ^[0-9]+$ ]] || fail "TMOD_CRASH_LOG_LINES must be a non-negative integer."
export TMOD_LOG_LEVEL TMOD_CRASH_LOG_LINES

mkdir -p /data/tModLoader/Logs
printf '[SYSTEM] Persistent tModLoader logs: /data/tModLoader/Logs\n'
printf '[SYSTEM] Console log level: %s; raw output: /data/tModLoader/Logs/container-console.log\n' "$TMOD_LOG_LEVEL"
printf '[SYSTEM] Shutdown message: configured; autosave interval: %s minute(s)\n' "$TMOD_AUTOSAVE_INTERVAL"

trap shutdown TERM INT

if use_custom_config; then
    [[ -f "$custom_config_path" ]] || fail "TMOD_USECONFIGFILE is enabled, but $custom_config_path was not found."
    config_path="$custom_config_path"
    printf '[CONFIG] Using the mounted custom configuration file.\n'
else
    load_password_file
    ./prepare-config.sh
fi

# tModLoader logs its entire child-process environment. The password is already
# in the generated configuration and must not be copied into environment logs.
unset TMOD_PASS TMOD_PASS_FILE

# Download missing/outdated Workshop items and enable the requested mods.
./manage-mods.sh

rm -f "$pipe" "$status_path"
mkfifo "$pipe"

printf '[SYSTEM] Launching tModLoader with %s\n' "$config_path"
cat "$pipe" &
cat_pid=$!
tmux new-session -d -s tmodloader /terraria-server/run-server.sh "$config_path" "$pipe" "$status_path"

if ((10#$TMOD_AUTOSAVE_INTERVAL > 0)); then
    /terraria-server/autosave.sh &
    autosave_pid=$!
else
    printf '[SYSTEM] Scheduled autosave commands are disabled.\n'
fi

wait "$cat_pid" || true
stop_autosave

status_deadline=$((SECONDS + 10))
while [[ ! -s "$status_path" ]] && tmux has-session -t tmodloader 2>/dev/null && ((SECONDS < status_deadline)); do
    sleep 0.1
done

server_status=1
if [[ -s "$status_path" ]]; then
    read -r server_status < "$status_path"
fi
rm -f "$pipe" "$status_path"

if [[ "$server_status" != "0" ]]; then
    printf '[!!] tModLoader exited unexpectedly with status %s.\n' "$server_status" >&2
fi
exit "$server_status"
