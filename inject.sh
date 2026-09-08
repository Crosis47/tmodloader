#!/bin/sh

# This file will send input from the docker exec to the console.
if ! tmux has-session -t tmodloader 2>/dev/null; then
    echo "tModLoader console is not running." >&2
    exit 1
fi

tmux send-keys -t tmodloader -l -- "$*"
tmux send-keys -t tmodloader Enter
