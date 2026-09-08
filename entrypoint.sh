#!/usr/bin/env bash

set -Eeuo pipefail

runtime_dir="${TMOD_RUNTIME_DIR:-/tmp/tmodloader}"
control_pipe="${TMOD_CONTROL_PIPE:-$runtime_dir/console}"
pid_path="${TMOD_SERVER_PID_FILE:-$runtime_dir/server.pid}"
generated_config_path="/terraria-server/serverconfig.txt"
custom_config_path="/terraria-server/customconfig.txt"
config_path="$generated_config_path"
server_runner="${TMOD_SERVER_RUNNER:-/terraria-server/run-server.sh}"
server_pid=""
autosave_pid=""
shutdown_requested=0

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

describe_path_access() {
    local path="$1"

    if [[ -e "$path" ]]; then
        stat --format='owner=%u:%g mode=%a' -- "$path" 2>/dev/null || printf 'owner/mode unavailable'
    else
        printf 'path does not exist'
    fi
}

ensure_writable_directory() {
    local path="$1"
    local probe
    local details

    if ! mkdir -p "$path" 2>/dev/null; then
        details="$(describe_path_access "$path")"
        fail "Cannot create $path as uid $(id -u), gid $(id -g), groups $(id -G) ($details). Check the mounted directory and parent permissions."
    fi
    if ! probe="$(mktemp "$path/.tmodloader-write-test.XXXXXX" 2>/dev/null)"; then
        details="$(describe_path_access "$path")"
        fail "$path is not writable as uid $(id -u), gid $(id -g), groups $(id -G) ($details). Grant write and search access through the applicable owner, group, ACL, or other permission class."
    fi
    rm -f "$probe"
}

server_is_running() {
    [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null
}

stop_autosave() {
    if [[ -n "$autosave_pid" ]] && kill -0 "$autosave_pid" 2>/dev/null; then
        kill "$autosave_pid" 2>/dev/null || true
        wait "$autosave_pid" 2>/dev/null || true
    fi
    autosave_pid=""
}

signal_server_group() {
    local signal="$1"

    [[ -n "$server_pid" ]] || return 0
    kill "-$signal" -- "-$server_pid" 2>/dev/null || kill "-$signal" "$server_pid" 2>/dev/null || true
}

wait_for_server_exit() {
    local deadline="$1"

    while server_is_running && ((SECONDS < deadline)); do
        sleep 0.25
    done
    ! server_is_running
}

shutdown() {
    local deadline

    if ((shutdown_requested)); then
        return
    fi
    shutdown_requested=1
    trap '' TERM INT
    stop_autosave

    if server_is_running; then
        inject "say $TMOD_SHUTDOWN_MESSAGE" || true
        sleep 3
        inject "exit" || true
        deadline=$((SECONDS + ${TMOD_SHUTDOWN_TIMEOUT:-90}))
        if ! wait_for_server_exit "$deadline"; then
            printf '[!!] Graceful shutdown timed out; terminating the server process group.\n' >&2
            signal_server_group TERM
            wait_for_server_exit "$((SECONDS + 5))" || signal_server_group KILL
        fi
        wait "$server_pid" 2>/dev/null || true
        server_pid=""
    fi

    exit 0
}

cleanup() {
    stop_autosave
    if server_is_running; then
        signal_server_group KILL
        wait "$server_pid" 2>/dev/null || true
    fi
    server_pid=""
    if [[ -e "/proc/$$/fd/3" ]]; then
        exec 3>&-
    fi
    rm -f "$control_pipe" "$pid_path"
}

[[ "$(id -u)" != "0" ]] || fail "The server refuses to run as root. Use the image's built-in tml user."
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
export TMOD_LOG_LEVEL TMOD_CRASH_LOG_LINES TMOD_CONTROL_PIPE TMOD_SERVER_PID_FILE

ensure_writable_directory /data
ensure_writable_directory /data/steamMods
ensure_writable_directory /data/tModLoader/Logs
ensure_writable_directory /data/tModLoader/ModConfigs
ensure_writable_directory /data/tModLoader/Mods
ensure_writable_directory /data/tModLoader/Worlds
ensure_writable_directory /terraria-server
ensure_writable_directory "$HOME"
install -d -m 0700 "$runtime_dir"

printf '[SYSTEM] Runtime identity: uid=%s gid=%s; init: tini; supervisor: direct PID\n' "$(id -u)" "$(id -g)"
printf '[SYSTEM] Persistent tModLoader logs: /data/tModLoader/Logs\n'
printf '[SYSTEM] Console log level: %s; raw output: /data/tModLoader/Logs/container-console.log\n' "$TMOD_LOG_LEVEL"
printf '[SYSTEM] Shutdown message: configured; autosave interval: %s minute(s)\n' "$TMOD_AUTOSAVE_INTERVAL"

trap shutdown TERM INT
trap cleanup EXIT

if use_custom_config; then
    [[ -f "$custom_config_path" ]] || fail "TMOD_USECONFIGFILE is enabled, but $custom_config_path was not found."
    [[ -r "$custom_config_path" ]] || fail "$custom_config_path is not readable by uid $(id -u)."
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

rm -f "$control_pipe" "$pid_path"
mkfifo -m 0600 "$control_pipe"
# Holding the FIFO open read/write prevents startup and command writers from
# blocking while the server process inherits its read end as standard input.
exec 3<> "$control_pipe"

printf '[SYSTEM] Launching tModLoader with %s\n' "$config_path"
setsid --wait "$server_runner" "$config_path" <&3 &
server_pid=$!
printf '%s\n' "$server_pid" > "$pid_path"

if ((10#$TMOD_AUTOSAVE_INTERVAL > 0)); then
    /terraria-server/autosave.sh &
    autosave_pid=$!
else
    printf '[SYSTEM] Scheduled autosave commands are disabled.\n'
fi

set +e
wait "$server_pid"
server_status=$?
set -e
server_pid=""
rm -f "$pid_path"
stop_autosave

if [[ "$server_status" != "0" ]]; then
    printf '[!!] tModLoader exited unexpectedly with status %s.\n' "$server_status" >&2
fi
exit "$server_status"
