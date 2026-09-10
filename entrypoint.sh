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
admin_pid=""
admin_failed=0
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
    if [[ -n "$admin_pid" ]]; then
        kill "$admin_pid" 2>/dev/null || true
        wait "$admin_pid" 2>/dev/null || true
    fi
    if server_is_running; then
        signal_server_group KILL
        wait "$server_pid" 2>/dev/null || true
    fi
    server_pid=""
    if [[ -e "/proc/$$/fd/3" ]]; then
        exec 3>&-
    fi
    rm -f "$control_pipe" "$pid_path" "$runtime_dir/supervisor.pid"
}

[[ "$(id -u)" != "0" ]] || fail "The server refuses to run as root. Use the image's built-in tml user."
admin_exports="$(python3 /terraria-server/admin_settings.py boot)" || fail "Invalid web-managed configuration."
# Only allowlisted keys and shlex-quoted values are emitted by admin_settings.
eval "$admin_exports"
unset admin_exports
[[ "${TMOD_WEB_ENABLED:-0}" =~ ^[01]$ ]] || fail "TMOD_WEB_ENABLED must be 0 or 1."
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
ensure_writable_directory /data/.tmod-control
exec 9>/data/.tmod-control/server.lock
flock -n 9 || fail "Another server or restore is using /data."
[[ ! -e /data/.tmod-control/restore-pending ]] || fail "An interrupted restore requires recovery; inspect /data/.tmod-control/restore-pending before starting."
[[ "${TMOD_BACKUP_INTERVAL:-0}" =~ ^[0-9]{1,7}$ ]] || fail "TMOD_BACKUP_INTERVAL must be a non-negative integer (minutes, maximum 9999999)."
[[ "${TMOD_BACKUP_KEEP:-7}" =~ ^[1-9][0-9]{0,5}$ ]] || fail "TMOD_BACKUP_KEEP must be a positive integer (maximum 999999)."
[[ "${TMOD_BACKUP_MIN_FREE_MB:-1024}" =~ ^[0-9]{1,9}$ ]] || fail "TMOD_BACKUP_MIN_FREE_MB must be a non-negative integer (maximum 999999999)."
backup_interval=$((10#${TMOD_BACKUP_INTERVAL:-0} * 60))
if ((backup_interval > 0)); then
    tmod-backup _preflight || fail "Scheduled backups require a writable /backups mount."
fi
ensure_writable_directory /data/steamMods
ensure_writable_directory /data/tModLoader/Logs
ensure_writable_directory /data/tModLoader/ModConfigs
ensure_writable_directory /data/tModLoader/Mods
ensure_writable_directory /data/tModLoader/Worlds
ensure_writable_directory /terraria-server
ensure_writable_directory "$HOME"
install -d -m 0700 "$runtime_dir"
python3 /terraria-server/admin_settings.py snapshot
python3 /terraria-server/admin_metrics.py startup
printf '%s\n' "$$" > "$runtime_dir/supervisor.pid"
rm -f "$runtime_dir/backup-request" "$runtime_dir/backup-result"

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

if [[ "${TMOD_WEB_ENABLED:-0}" == 1 ]]; then
    python3 /terraria-server/admin_server.py &
    admin_pid=$!
    sleep 1
    kill -0 "$admin_pid" 2>/dev/null || fail "Admin interface could not start. Check its origin and secret file."
fi

# Download missing/outdated Workshop items and enable the requested mods.
./manage-mods.sh
python3 /terraria-server/admin_settings.py snapshot

rm -f "$control_pipe" "$pid_path"
mkfifo -m 0600 "$control_pipe"
# Holding the FIFO open read/write prevents startup and command writers from
# blocking while the server process inherits its read end as standard input.
exec 3<> "$control_pipe"

start_server() {
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
}

perform_backup() {
    local request_id="$1" status=0 deadline archive
    python3 /terraria-server/admin_metrics.py running "Preparing cold backup" || true
    if ! healthcheck; then
        python3 /terraria-server/admin_metrics.py failed "Server is not healthy; backup was not started" || true
        printf '%s\n1\nServer is not healthy; backup was not started.\n' "$request_id" > "$runtime_dir/backup-result.tmp"
        mv "$runtime_dir/backup-result.tmp" "$runtime_dir/backup-result"
        return
    fi
    if ! tmod-backup _preflight; then
        python3 /terraria-server/admin_metrics.py failed "Backup mount or free-space check failed; server was not stopped" || true
        printf '%s\n1\nBackup preflight failed; inspect storage and container logs.\n' "$request_id" > "$runtime_dir/backup-result.tmp"
        mv "$runtime_dir/backup-result.tmp" "$runtime_dir/backup-result"
        return
    fi
    stop_autosave
    printf '[BACKUP] Stopping the game process for a consistent backup.\n'
    inject "say Server restarting for backup." || true
    inject "exit" || true
    deadline=$((SECONDS + ${TMOD_SHUTDOWN_TIMEOUT:-90}))
    if ! wait_for_server_exit "$deadline"; then
        printf '[BACKUP] Graceful stop timed out; skipping backup.\n' >&2
        signal_server_group TERM
        wait_for_server_exit "$((SECONDS + 5))" || signal_server_group KILL
        status=1
    fi
    wait "$server_pid" || status=1
    server_pid=""
    rm -f "$pid_path" "$runtime_dir/backup-archive"
    if ((status == 0)); then
        tmod-backup _cold || status=1
    fi
    # Drain any queued commands from the previous server before restarting.
    exec 3>&-
    rm -f "$control_pipe"
    mkfifo -m 0600 "$control_pipe"
    exec 3<> "$control_pipe"
    start_server
    deadline=$((SECONDS + 600))
    while ! healthcheck; do
        if ! server_is_running || ((SECONDS >= deadline)); then
            printf '[BACKUP] Server failed restart health validation.\n' >&2
            status=1
            break
        fi
        sleep 2
    done
    if ((status == 0)); then
        archive="$(<"$runtime_dir/backup-archive")"
        tmod-backup _retain --archive "$archive" || status=1
    fi
    printf '%s\n%s\nBackup status: %s (0=success); inspect container logs for details.\n' \
        "$request_id" "$status" "$status" > "$runtime_dir/backup-result.tmp"
    mv "$runtime_dir/backup-result.tmp" "$runtime_dir/backup-result"
    printf '[BACKUP] Finished with status %s.\n' "$status"
    if ((status == 0)); then
        python3 /terraria-server/admin_metrics.py success "Backup verified and game restart validated" || true
    else
        python3 /terraria-server/admin_metrics.py failed "Backup or game restart failed; inspect container logs" || true
    fi
}

admin_progress() {
    jq -n --arg id "$request_id" --arg stage "$1" --arg detail "$2" '{id:$id,stage:$stage,detail:$detail}' > "$runtime_dir/admin-progress.tmp"
    mv "$runtime_dir/admin-progress.tmp" "$runtime_dir/admin-progress"
}

perform_admin_apply() {
    local request_id="$1" status=0 deadline
    admin_progress stopping 'Saving the world and stopping the game. Players will disconnect.'
    stop_autosave
    if server_is_running; then
        inject "say Server restarting to apply administrator changes." || true
        inject "exit" || true
        if ! wait_for_server_exit "$((SECONDS + ${TMOD_SHUTDOWN_TIMEOUT:-90}))"; then
            signal_server_group TERM
            wait_for_server_exit "$((SECONDS + 5))" || signal_server_group KILL
            status=1
        fi
        wait "$server_pid" || status=1
    fi
    server_pid=""
    rm -f "$pid_path"
    if ((status == 0)); then
        admin_progress settings 'Validating and writing the staged server configuration.'
        if TMOD_ADMIN_REQUEST_ID="$request_id" python3 /terraria-server/admin_settings.py apply; then
            # shellcheck disable=SC1091
            source "$runtime_dir/admin.env"
            admin_progress mods 'Resolving Workshop selections and checking/downloading mods. This may take several minutes.'
            TMOD_ADMIN_REQUEST_ID="$request_id" ./manage-mods.sh || status=1
        else
            status=1
        fi
    fi
    if ((status == 0)); then
        admin_progress starting 'Starting the game with the new configuration.'
        exec 3>&-
        rm -f "$control_pipe"
        mkfifo -m 0600 "$control_pipe"
        exec 3<> "$control_pipe"
        start_server
        admin_progress health 'Waiting for world loading and the game listener to become healthy (up to 10 minutes).'
        deadline=$((SECONDS + 600))
        while ! healthcheck; do
            if ! server_is_running || ((SECONDS >= deadline)); then
                status=1
                break
            fi
            sleep 2
        done
    fi
    if ((status != 0)); then
        if server_is_running; then
            signal_server_group TERM
            wait_for_server_exit "$((SECONDS + 5))" || signal_server_group KILL
            wait "$server_pid" 2>/dev/null || true
        fi
        stop_autosave
        server_pid=""
        rm -f "$pid_path"
        admin_failed=1
        printf '[ADMIN] Apply failed. Game stopped; correct settings in the dashboard and apply again.\n' >&2
    else
        admin_failed=0
        rm -f /data/admin/pending.json
        python3 /terraria-server/admin_settings.py snapshot
        printf '[ADMIN] Settings applied and game health validated.\n'
    fi
    backup_interval=$((10#${TMOD_BACKUP_INTERVAL:-0} * 60))
    next_backup=$((SECONDS + backup_interval))
    jq -n --arg id "$request_id" --argjson status "$status" '{id:$id,status:$status}' > "$runtime_dir/admin-result.tmp"
    mv "$runtime_dir/admin-result.tmp" "$runtime_dir/admin-result"
}

start_server
next_backup=$((SECONDS + backup_interval))
while server_is_running || ((admin_failed)); do
    if [[ -n "$admin_pid" ]] && ! kill -0 "$admin_pid" 2>/dev/null; then
        fail "Admin interface exited unexpectedly; inspect container logs."
    fi
    if [[ -f "$runtime_dir/admin-request" ]]; then
        request_id="$(jq -r .id "$runtime_dir/admin-request")"
        rm -f "$runtime_dir/admin-request"
        perform_admin_apply "$request_id"
    elif [[ -f "$runtime_dir/backup-request" ]]; then
        request_id="$(<"$runtime_dir/backup-request")"
        rm -f "$runtime_dir/backup-request"
        perform_backup "$request_id"
        next_backup=$((SECONDS + backup_interval))
    elif ((backup_interval > 0 && SECONDS >= next_backup)); then
        if healthcheck; then
            perform_backup scheduled
            next_backup=$((SECONDS + backup_interval))
        else
            next_backup=$((SECONDS + 30))
        fi
    fi
    sleep 1
done

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
