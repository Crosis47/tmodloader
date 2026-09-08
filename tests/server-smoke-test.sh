#!/usr/bin/env bash

set -Eeuo pipefail

image="${1:-tmodloader:ci}"
timeout_seconds="${TMOD_SMOKE_TIMEOUT:-600}"
suffix="${GITHUB_RUN_ID:-local}-$RANDOM-$$"
container_name="tmodloader-smoke-$suffix"
volume_name="tmodloader-smoke-$suffix"
root_probe_name="tmodloader-root-probe-$suffix"
readonly_probe_name="tmodloader-readonly-probe-$suffix"

case "$(uname -s)" in
    MINGW*|MSYS*) export MSYS_NO_PATHCONV=1 ;;
esac

cleanup() {
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    docker rm --force "$root_probe_name" >/dev/null 2>&1 || true
    docker rm --force "$readonly_probe_name" >/dev/null 2>&1 || true
    docker volume rm "$volume_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$volume_name" >/dev/null

root_output="$(timeout 20 docker run --rm \
    --name "$root_probe_name" \
    --user 0:0 \
    "$image" 2>&1 || true)"
if ! grep -Fq "refuses to run as root" <<<"$root_output"; then
    echo "Expected the image to reject a root runtime override." >&2
    printf '%s\n' "$root_output" >&2
    exit 1
fi

readonly_output="$(timeout 20 docker run --rm \
    --name "$readonly_probe_name" \
    --mount "type=volume,source=$volume_name,target=/data,readonly" \
    "$image" 2>&1 || true)"
if ! grep -Fq "/data is not writable" <<<"$readonly_output"; then
    echo "Expected a precise diagnostic for a read-only /data volume." >&2
    printf '%s\n' "$readonly_output" >&2
    exit 1
fi

docker run --detach \
    --name "$container_name" \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=64m,mode=1777 \
    --mount "type=volume,source=$volume_name,target=/data" \
    --env TMOD_PASS=N/A \
    --env TMOD_MODS= \
    --env TMOD_WORLDNAME=SmokeTest \
    --env TMOD_WORLDSIZE=1 \
    --env TMOD_DIFFICULTY=0 \
    --env TMOD_AUTOSAVE_INTERVAL=0 \
    --env TMOD_LOG_LEVEL=normal \
    --env 'TMOD_SHUTDOWN_MESSAGE=Smoke test shutdown' \
    "$image" >/dev/null

deadline=$((SECONDS + timeout_seconds))
health_status="starting"
while ((SECONDS < deadline)); do
    container_status="$(docker inspect --format '{{.State.Status}}' "$container_name")"
    if [[ "$container_status" == "exited" || "$container_status" == "dead" ]]; then
        docker logs "$container_name" >&2
        echo "Smoke-test container exited before becoming healthy." >&2
        exit 1
    fi
    health_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_name")"
    [[ "$health_status" != "healthy" ]] || break
    sleep 5
done

if [[ "$health_status" != "healthy" ]]; then
    docker logs "$container_name" >&2
    echo "Smoke-test container did not become healthy within $timeout_seconds seconds." >&2
    exit 1
fi

[[ "$(docker inspect --format '{{.Config.User}}' "$container_name")" == "tml:tml" ]]
[[ "$(docker exec "$container_name" id -u)" == "1000" ]]
[[ "$(docker exec "$container_name" id -g)" == "1000" ]]
[[ "$(docker exec "$container_name" cat /proc/1/comm)" == "tini" ]]
if docker exec "$container_name" sh -c 'command -v tmux' >/dev/null 2>&1; then
    echo "tmux is still installed in the runtime image." >&2
    exit 1
fi
docker exec "$container_name" sh -c \
    'server_pid="$(cat /tmp/tmodloader/server.pid)" && test -n "$server_pid" && kill -0 "$server_pid"'
[[ "$(docker inspect --format '{{json .HostConfig.CapDrop}}' "$container_name")" == '["ALL"]' ]]
[[ "$(docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$container_name")" == *'no-new-privileges'* ]]

docker exec "$container_name" inject "say Docker smoke test passed."
docker exec "$container_name" test -s /data/tModLoader/Logs/server.log
docker exec "$container_name" test -s /data/tModLoader/Logs/container-console.log
if docker exec "$container_name" grep -R -Fq 'TMOD_PASS=' /data/tModLoader/Logs; then
    echo "The server password variable leaked into a tModLoader environment log." >&2
    exit 1
fi

console_output="$(docker logs "$container_name" 2>&1)"
if grep -Fq 'Launch command:' <<< "$console_output"; then
    echo "Normal console logging exposed the upstream launch command." >&2
    exit 1
fi
if grep -Eq '^[[:digit:]]+([.][[:digit:]]+)?% - .+ - [[:digit:]]+([.][[:digit:]]+)?%$' <<< "$console_output"; then
    echo "Normal console logging exposed high-frequency world-generation progress." >&2
    exit 1
fi
docker exec "$container_name" grep -Fq 'Launch command:' /data/tModLoader/Logs/container-console.log

docker stop --time 120 "$container_name" >/dev/null
exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$container_name")"
if [[ "$exit_code" != "0" ]]; then
    docker logs "$container_name" >&2
    echo "Smoke-test container stopped with exit code $exit_code." >&2
    exit 1
fi

docker run --rm \
    --entrypoint bash \
    --mount "type=volume,source=$volume_name,target=/data" \
    "$image" \
    -lc "test -s /data/tModLoader/Logs/server.log && grep -Fq 'Server started' /data/tModLoader/Logs/server.log"

echo "server smoke test passed."
