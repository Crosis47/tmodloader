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
# A second run must recognize the downloaded manifest without downloading again.
output="$(bash /terraria-server/manage-mods.sh 2>&1)"
printf '%s\n' "$output"
grep -Fq 'All requested mods are already current' <<< "$output"
echo "Live Workshop download and cache reuse passed."
