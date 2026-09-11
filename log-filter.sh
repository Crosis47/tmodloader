#!/usr/bin/env bash

set -Eeuo pipefail

mode="${1:-normal}"
last_world_stage=""
launcher_startup=true

case "$mode" in
    quiet|normal|debug) ;;
    *)
        printf '[!!] Invalid console log level: %s\n' "$mode" >&2
        exit 64
        ;;
esac

if [[ "$mode" == "debug" ]]; then
    cat
    exit 0
fi

while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"

    # Explicit world creation starts a second launcher after saving the world.
    if [[ "$line" == *"[WORLDGEN] World saved;"* ]]; then
        launcher_startup=true
    fi

    if [[ "$mode" == "quiet" ]]; then
        lower_line="${line,,}"
        case "$lower_line" in
            *warning*|*error*|*fatal*|*exception*|*crash*|*failed*|*failure*|*unable*|*"out of memory"*|*"server started"*|*"listening on port"*|*"saving world"*|*"world saved"*)
                printf '%s\n' "$line"
                ;;
        esac
        continue
    fi

    if [[ "$launcher_startup" == true ]]; then
        case "$line" in
            ""|"You are on platform:"*|"Logging to "*|"Fixing Environment Issues"*|"Success!"*|"Verifying .NET"*|"This may take"*|"Parsing .NET"*|"Checking for old .NET"*|"Cleanup Complete"*|"Checking dotnet install"*|"Dotnet should be present"*|"Attempting Launch"*)
                continue
                ;;
            "Launched Using "*)
                launcher_startup=false
                continue
                ;;
        esac
    fi

    # tModLoader can print tens of thousands of sub-percent world-generation
    # updates. Keep one line per stage in normal mode instead.
    if [[ "$line" =~ ^[[:digit:]]+([.][[:digit:]]+)?%[[:space:]]+-[[:space:]]+(.*)[[:space:]]+-[[:space:]]+[[:digit:]]+([.][[:digit:]]+)?%$ ]]; then
        world_stage="${BASH_REMATCH[2]}"
        world_stage="${world_stage% }"
        if [[ -n "$world_stage" && "$world_stage" != "$last_world_stage" ]]; then
            printf '[WORLD] %s\n' "$world_stage"
            last_world_stage="$world_stage"
        fi
        continue
    fi

    # The TCP healthcheck connects from loopback and immediately disconnects.
    # Its connection notice is operational noise, not a player event.
    if [[ "$line" =~ ^127\.0\.0\.1:[[:digit:]]+[[:space:]]+is[[:space:]]+connecting\.\.\.$ ]]; then
        continue
    fi

    printf '%s\n' "$line"
done
