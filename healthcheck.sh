#!/usr/bin/env bash

set -Eeuo pipefail

port="${TMOD_PORT:-7777}"
log_path="/data/tModLoader/Logs/server.log"
runtime_dir="${TMOD_RUNTIME_DIR:-/tmp/tmodloader}"
pid_path="${TMOD_SERVER_PID_FILE:-$runtime_dir/server.pid}"

[[ "$port" =~ ^[0-9]+$ ]]
[[ -r "$pid_path" ]]
read -r server_pid < "$pid_path"
[[ "$server_pid" =~ ^[1-9][0-9]*$ ]]
kill -0 "$server_pid" 2>/dev/null
[[ -s "$log_path" ]]
grep -Fq 'Server started' "$log_path"
timeout 3 bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1"' -- "$port"
