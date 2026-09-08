#!/usr/bin/env bash

set -Eeuo pipefail

if (($# != 3)); then
    printf 'Usage: %s CONTAINER_VERSION TMODLOADER_VERSION CHANNEL\n' "$0" >&2
    exit 2
fi

container_version="$1"
tml_version="$2"
channel="$3"
semver_component='(0|[1-9][0-9]*)'

if ! [[ "$container_version" =~ ^${semver_component}\.${semver_component}\.${semver_component}$ ]]; then
    printf '[!!] Invalid container SemVer core: %s\n' "$container_version" >&2
    exit 1
fi
if ! [[ "$tml_version" =~ ^v[0-9]{4}\.[0-9]{1,2}\.[0-9]+\.[0-9]+$ ]]; then
    printf '[!!] Invalid tModLoader release tag: %s\n' "$tml_version" >&2
    exit 1
fi
case "$channel" in
    stable|preview) ;;
    *)
        printf '[!!] Channel must be stable or preview: %s\n' "$channel" >&2
        exit 1
        ;;
esac

release_tag="${container_version}+tml.${tml_version}.${channel}"
docker_tag="${container_version}-tml-${tml_version//./-}-${channel}"
tml_tag="tml-${tml_version}-${channel}"
release_title="Container v${container_version} with tModLoader ${tml_version} (${channel})"

if ((${#docker_tag} > 128)); then
    printf '[!!] Generated Docker tag exceeds 128 characters: %s\n' "$docker_tag" >&2
    exit 1
fi

emit_output() {
    local key="$1"
    local value="$2"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        printf '%s=%s\n' "$key" "$value" >> "$GITHUB_OUTPUT"
    else
        printf '%s=%s\n' "$key" "$value"
    fi
}

emit_output container_version "$container_version"
emit_output tml_version "$tml_version"
emit_output channel "$channel"
emit_output release_tag "$release_tag"
emit_output docker_tag "$docker_tag"
emit_output tml_tag "$tml_tag"
emit_output legacy_tag "$tml_version"
emit_output release_title "$release_title"
if [[ "$channel" == "preview" ]]; then
    emit_output prerelease true
else
    emit_output prerelease false
fi

printf '[RELEASE] %s -> %s\n' "$release_tag" "$docker_tag" >&2
