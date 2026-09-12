#!/usr/bin/env bash

set -Eeuo pipefail

steamcmd_under_test="${1:-/usr/bin/steamcmd}"

if [[ "$(locale charmap)" != "UTF-8" ]]; then
    echo "The runtime locale is not UTF-8." >&2
    exit 1
fi

if [[ "${TMOD_WORKSHOP_BACKEND:-steamcmd}" == depotdownloader ]]; then
    depotdownloader --version
    echo "Native Workshop downloader locale tests passed."
    exit 0
fi

if ! output="$("$steamcmd_under_test" /terraria-server +login anonymous +quit 2>&1)"; then
    printf '%s\n' "$output" >&2
    echo "SteamCMD failed during the locale regression test." >&2
    exit 1
fi

if grep -Eqi 'setlocale.*failed' <<<"$output"; then
    printf '%s\n' "$output" >&2
    echo "SteamCMD fell back from the configured UTF-8 locale." >&2
    exit 1
fi

echo "locale tests passed."
