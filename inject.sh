#!/bin/bash

set -Eeuo pipefail

if [[ "$(id -u)" == "0" ]]; then
    exec /usr/bin/setpriv --reuid=tml --regid=tml --init-groups --no-new-privs -- "$0" "$@"
fi

runtime_dir="${TMOD_RUNTIME_DIR:-/tmp/tmodloader}"
control_pipe="${TMOD_CONTROL_PIPE:-$runtime_dir/console}"
pid_path="${TMOD_SERVER_PID_FILE:-$runtime_dir/server.pid}"
command_text="$*"

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

[[ -n "$command_text" ]] || fail "A tModLoader console command is required."
if [[ "$command_text" == *$'\n'* || "$command_text" == *$'\r'* ]]; then
    fail "Console commands cannot contain line breaks."
fi
if ((${#command_text} > 4000)); then
    fail "Console commands cannot exceed 4000 characters."
fi
[[ -r "$pid_path" ]] || fail "tModLoader console is not running."
read -r server_pid < "$pid_path"
[[ "$server_pid" =~ ^[1-9][0-9]*$ ]] || fail "The tModLoader server PID file is invalid."
kill -0 "$server_pid" 2>/dev/null || fail "tModLoader console is not running."
[[ -p "$control_pipe" ]] || fail "The tModLoader console pipe is unavailable."

if ! timeout 5 bash -c 'printf "%s\n" "$1" > "$2"' -- "$command_text" "$control_pipe"; then
    fail "Timed out while sending the command to tModLoader."
fi
