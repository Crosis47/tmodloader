#!/usr/bin/env bash

set -Eeuo pipefail

port="${TMOD_PORT:-7777}"
log_path="/data/tModLoader/Logs/server.log"

[[ "$port" =~ ^[0-9]+$ ]]
tmux has-session -t tmodloader 2>/dev/null
[[ -s "$log_path" ]]
grep -Fq 'Server started' "$log_path"
timeout 3 bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1"' -- "$port"
