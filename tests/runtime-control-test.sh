#!/usr/bin/env bash

set -Eeuo pipefail

inject_under_test="${1:-/usr/local/bin/inject}"
test_root="$(mktemp -d)"
control_pipe="$test_root/console"
pid_path="$test_root/server.pid"
server_pid=""
reader_pid=""

cleanup() {
    if [[ -n "$reader_pid" ]]; then
        kill "$reader_pid" 2>/dev/null || true
        wait "$reader_pid" 2>/dev/null || true
    fi
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$test_root"
}
trap cleanup EXIT

mkfifo "$control_pipe"
sleep 30 &
server_pid=$!
printf '%s\n' "$server_pid" > "$pid_path"
cat "$control_pipe" > "$test_root/received" &
reader_pid=$!

TMOD_CONTROL_PIPE="$control_pipe" \
TMOD_SERVER_PID_FILE="$pid_path" \
bash "$inject_under_test" "say Hello World!"
wait "$reader_pid"
reader_pid=""
grep -Fxq 'say Hello World!' "$test_root/received"

if TMOD_CONTROL_PIPE="$control_pipe" \
    TMOD_SERVER_PID_FILE="$pid_path" \
    bash "$inject_under_test" $'say first\nsay second' >/dev/null 2>&1; then
    echo "A multiline console command unexpectedly passed validation." >&2
    exit 1
fi

kill "$server_pid"
wait "$server_pid" 2>/dev/null || true
server_pid=""
if TMOD_CONTROL_PIPE="$control_pipe" \
    TMOD_SERVER_PID_FILE="$pid_path" \
    bash "$inject_under_test" "save" >/dev/null 2>&1; then
    echo "A command was accepted for a stopped server." >&2
    exit 1
fi

printf '%s\n' 'not-a-pid' > "$pid_path"
if TMOD_CONTROL_PIPE="$control_pipe" \
    TMOD_SERVER_PID_FILE="$pid_path" \
    bash "$inject_under_test" "save" >/dev/null 2>&1; then
    echo "An invalid server PID file unexpectedly passed validation." >&2
    exit 1
fi

echo "runtime control tests passed."
