#!/usr/bin/env bash
# Online integration test, run inside either image as tml.
set -Eeuo pipefail
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
export TMOD_DATA_DIR="$test_root/data"
export TMOD_MODS="${TMOD_TEST_WORKSHOP_ID:-2619954303}"
export TMOD_MOD_OFFLINE_POLICY=strict
bash /terraria-server/manage-mods.sh
test -s "$TMOD_DATA_DIR/tModLoader/Mods/enabled.json"
jq -e 'length > 0' "$TMOD_DATA_DIR/tModLoader/Mods/enabled.json" >/dev/null
# A metadata timeout on the first download leaves the native cache deliberately
# unverified. Allow one verification download before requiring cache reuse.
for attempt in 1 2 3; do
    if output="$(bash /terraria-server/manage-mods.sh 2>&1)"; then
        printf '%s\n' "$output"
    else
        printf '%s\n' "$output" >&2
        exit 1
    fi
    if grep -Fq 'All requested mods are already current' <<< "$output"; then
        echo "Live Workshop download and cache reuse passed."
        exit 0
    fi
    echo "Cache not verified on attempt $attempt; checking again."
done
echo "Workshop cache reuse was not confirmed after three checks." >&2
exit 1
