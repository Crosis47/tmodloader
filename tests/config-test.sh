#!/usr/bin/env bash

set -Eeuo pipefail

script_under_test="${1:-/terraria-server/prepare-config.sh}"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
config_path="$test_root/serverconfig.txt"
secret='do-not-print-this-password'

output="$({
    TMOD_CONFIG_PATH="$config_path" \
    TMOD_DATA_DIR="$test_root/data" \
    TMOD_PASS="$secret" \
    bash "$script_under_test"
} 2>&1)"

if [[ "$output" == *"$secret"* ]]; then
    echo "prepare-config printed the server password." >&2
    exit 1
fi
grep -Fxq "password=$secret" "$config_path"
grep -Fxq 'port=7777' "$config_path"

if TMOD_CONFIG_PATH="$config_path" TMOD_DATA_DIR="$test_root/data" TMOD_PORT=70000 bash "$script_under_test"; then
    echo "An invalid port unexpectedly passed validation." >&2
    exit 1
fi

if TMOD_CONFIG_PATH="$config_path" TMOD_DATA_DIR="$test_root/data" TMOD_MOTD=$'hello\npassword=injected' bash "$script_under_test"; then
    echo "A multiline MOTD unexpectedly passed validation." >&2
    exit 1
fi

echo "configuration tests passed."
