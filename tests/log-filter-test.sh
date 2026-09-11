#!/usr/bin/env bash

set -Eeuo pipefail

filter_under_test="${1:-/terraria-server/log-filter.sh}"
runner_under_test="${2:-/terraria-server/run-server.sh}"
test_root="$(mktemp -d)"

cleanup() {
    rm -rf "$test_root"
}
trap cleanup EXIT

fixture="$test_root/fixture.log"
cat > "$fixture" <<'EOF'
You are on platform: Linux
Logging to /data/tModLoader/Logs
Fixing Environment Issues
Success!
Verifying .NET...
Attempting Launch...
Launched Using Local Dotnet. Launch command: dotnet tModLoader.dll -server
Finding Mods...
0.0% - Generating world terrain - 0.1%
0.0% - Generating world terrain - 0.2%
0.0% - Resetting game objects - 0.3%
127.0.0.1:45678 is connecting...
Listening on port 7777
Server started
Ordinary player chat
ERROR: illustrative failure
Choose World:[WORLDGEN] World saved; starting the configured game server.
You are on platform: Linux
Attempting Launch...
Launched Using Local Dotnet. Launch command: dotnet tModLoader.dll -server
Server started
EOF

bash "$filter_under_test" debug < "$fixture" > "$test_root/debug.log"
cmp "$fixture" "$test_root/debug.log"

bash "$filter_under_test" normal < "$fixture" > "$test_root/normal.log"
! grep -Fq 'Launch command:' "$test_root/normal.log"
! grep -Fq '0.0% -' "$test_root/normal.log"
! grep -Fq '127.0.0.1:45678 is connecting' "$test_root/normal.log"
[[ "$(grep -Fxc '[WORLD] Generating world terrain' "$test_root/normal.log")" == "1" ]]
[[ "$(grep -Fxc '[WORLD] Resetting game objects' "$test_root/normal.log")" == "1" ]]
grep -Fxq 'Finding Mods...' "$test_root/normal.log"
grep -Fxq 'Ordinary player chat' "$test_root/normal.log"

bash "$filter_under_test" quiet < "$fixture" > "$test_root/quiet.log"
grep -Fxq 'Listening on port 7777' "$test_root/quiet.log"
grep -Fxq 'Server started' "$test_root/quiet.log"
grep -Fxq 'ERROR: illustrative failure' "$test_root/quiet.log"
! grep -Fq 'Finding Mods...' "$test_root/quiet.log"
! grep -Fq 'Ordinary player chat' "$test_root/quiet.log"

if bash "$filter_under_test" verbose < "$fixture" >/dev/null 2>&1; then
    echo "An invalid log level unexpectedly passed validation." >&2
    exit 1
fi

mock_caller="$test_root/mock-caller.sh"
cat > "$mock_caller" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'Launched Using Local Dotnet. Launch command: dotnet tModLoader.dll -server'
printf '%s\n' '0.0% - Generating world terrain - 0.1%'
printf '%s\n' 'FATAL: simulated server crash'
exit 42
EOF

mkdir -p "$test_root/logs"
: > "$test_root/serverconfig.txt"
printf '%s\n' 'previous launch' > "$test_root/logs/container-console.log"
printf '%s\n' 'oldest launch' > "$test_root/logs/container-console.previous.log"
printf '%s\n' '2026-09-01T00:00:00+00:00' > "$test_root/logs/container-console.previous.log.first"
printf '%s\n' '2026-09-02T00:00:00+00:00' > "$test_root/logs/container-console.log.first"

set +e
TMOD_SCRIPT_CALLER="$mock_caller" \
TMOD_LOG_FILTER="$filter_under_test" \
TMOD_LOG_DIR="$test_root/logs" \
TMOD_LOG_LEVEL=normal \
TMOD_CRASH_LOG_LINES=20 \
bash "$runner_under_test" "$test_root/serverconfig.txt" > "$test_root/crash-output.log" 2>&1
runner_status=$?
set -e

[[ "$runner_status" == "42" ]]
grep -Fq 'replaying the last 20 raw console lines' "$test_root/crash-output.log"
grep -Fq 'Launch command:' "$test_root/crash-output.log"
grep -Fq 'Launch command:' "$test_root/logs/container-console.log"
grep -Fxq 'previous launch' "$test_root/logs/container-console.previous.log"
grep -Fxq 'oldest launch' "$test_root"/logs/console-history/run-*.log
grep -Fxq '2026-09-01T00:00:00+00:00' "$test_root"/logs/console-history/run-*.log.first
grep -Fxq '2026-09-02T00:00:00+00:00' "$test_root/logs/container-console.previous.log.first"
test -s "$test_root/logs/container-console.log.first"

echo "console log filter tests passed."
