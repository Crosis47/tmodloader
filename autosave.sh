#!/usr/bin/env bash

set -Eeuo pipefail

interval="${TMOD_AUTOSAVE_INTERVAL:-10}"
[[ "$interval" =~ ^[1-9][0-9]*$ ]] || {
    printf '[!!] TMOD_AUTOSAVE_INTERVAL must be a positive integer when autosave is enabled.\n' >&2
    exit 1
}

while sleep "${interval}m"; do
    printf '[SYSTEM] Requesting a scheduled world save.\n'
    inject "say Scheduled world save starting."
    inject "save"
done
