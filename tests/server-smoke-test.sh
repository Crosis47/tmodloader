#!/usr/bin/env bash

set -Eeuo pipefail

image="${1:-tmodloader:ci}"
timeout_seconds="${TMOD_SMOKE_TIMEOUT:-600}"
suffix="${GITHUB_RUN_ID:-local}-$RANDOM-$$"
container_name="tmodloader-smoke-$suffix"
volume_name="tmodloader-smoke-$suffix"

case "$(uname -s)" in
    MINGW*|MSYS*) export MSYS_NO_PATHCONV=1 ;;
esac

cleanup() {
    docker rm --force "$container_name" >/dev/null 2>&1 || true
    docker volume rm "$volume_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "$volume_name" >/dev/null
docker run --detach \
    --name "$container_name" \
    --mount "type=volume,source=$volume_name,target=/data" \
    --env TMOD_PASS=N/A \
    --env TMOD_MODS= \
    --env TMOD_WORLDNAME=SmokeTest \
    --env TMOD_WORLDSIZE=1 \
    --env TMOD_DIFFICULTY=0 \
    --env TMOD_AUTOSAVE_INTERVAL=0 \
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

docker exec "$container_name" inject "say Docker smoke test passed."
docker exec "$container_name" test -s /data/tModLoader/Logs/server.log
if docker exec "$container_name" grep -R -Fq 'TMOD_PASS=' /data/tModLoader/Logs; then
    echo "The server password variable leaked into a tModLoader environment log." >&2
    exit 1
fi

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
