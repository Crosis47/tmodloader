#!/usr/bin/env bash

set -Eeuo pipefail

interval="${TMOD_AUTOSAVE_INTERVAL:-10}"
message="${TMOD_AUTOSAVE_MESSAGE-Scheduled world save starting.}"
[[ "$interval" =~ ^[1-9][0-9]*$ ]] || {
    printf '[!!] TMOD_AUTOSAVE_INTERVAL must be a positive integer when autosave is enabled.\n' >&2
    exit 1
}
if [[ "$message" == *$'\n'* || "$message" == *$'\r'* ]]; then
    printf '[!!] TMOD_AUTOSAVE_MESSAGE cannot contain line breaks.\n' >&2
    exit 1
fi

while sleep "${interval}m"; do
    printf '[SYSTEM] Requesting a scheduled world save.\n'
    if [[ -n "$message" ]]; then
        inject "say $message" || true
    fi
    inject "save"
done
