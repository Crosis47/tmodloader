#!/usr/bin/env bash

set -Eeuo pipefail

port="${TMOD_PORT:-7777}"
log_path="/data/tModLoader/Logs/server.log"
runtime_dir="${TMOD_RUNTIME_DIR:-/tmp/tmodloader}"
pid_path="${TMOD_SERVER_PID_FILE:-$runtime_dir/server.pid}"

[[ "$port" =~ ^[0-9]+$ ]]
((10#$port >= 1 && 10#$port <= 65535))
[[ -r "$pid_path" ]]
read -r server_pid < "$pid_path"
[[ "$server_pid" =~ ^[1-9][0-9]*$ ]]
kill -0 "$server_pid" 2>/dev/null
[[ -s "$log_path" ]]
grep -Fq 'Server started' "$log_path"
# A TCP connect/close is counted as an anonymous Terraria player until its
# handshake expires. Dashboard polling can fill all slots and stop the listener.
# Inspect readiness without making connections or consuming player slots.
printf -v port_hex '%04X' "$((10#$port))"
for socket_table in /proc/net/tcp /proc/net/tcp6; do
    [[ -r "$socket_table" ]] || continue
    while read -r _ local_address _ socket_state _; do
        if [[ "$local_address" == *":$port_hex" && "$socket_state" == 0A ]]; then
            exit 0
        fi
    done < "$socket_table"
done
exit 1
