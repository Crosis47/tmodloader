#!/usr/bin/env bash

set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
metadata_script="${1:-$repository_root/release-metadata.sh}"
notes_script="${2:-$repository_root/release-notes.sh}"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
metadata_output="$test_root/metadata"
preview_metadata_output="$test_root/preview-metadata"
notes_output="$test_root/notes.md"
manual_notes_output="$test_root/manual-notes.md"
current_version="$(tr -d '\r\n' < "$repository_root/VERSION")"

GITHUB_OUTPUT="$metadata_output" \
    bash "$metadata_script" 1.2.3 v2026.07.3.0 stable

grep -Fxq 'release_tag=1.2.3+tml.v2026.07.3.0.stable' "$metadata_output"
grep -Fxq 'docker_tag=1.2.3-tml-v2026-07-3-0-stable' "$metadata_output"
grep -Fxq 'tml_tag=tml-v2026.07.3.0-stable' "$metadata_output"
grep -Fxq 'legacy_tag=v2026.07.3.0' "$metadata_output"
grep -Fxq 'prerelease=false' "$metadata_output"

GITHUB_OUTPUT="$preview_metadata_output" \
    bash "$metadata_script" 1.2.3 v2026.08.2.1 preview
grep -Fxq 'release_tag=1.2.3+tml.v2026.08.2.1.preview' "$preview_metadata_output"
grep -Fxq 'docker_tag=1.2.3-tml-v2026-08-2-1-preview' "$preview_metadata_output"
grep -Fxq 'prerelease=true' "$preview_metadata_output"

docker_tag="$(sed -n 's/^docker_tag=//p' "$metadata_output")"
if ! [[ "$docker_tag" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[0-9A-Za-z-]+$ ]]; then
    printf 'Generated Docker tag is not valid SemVer: %s\n' "$docker_tag" >&2
    exit 1
fi

if bash "$metadata_script" 01.2.3 v2026.07.3.0 stable; then
    echo 'A container version with a leading zero unexpectedly passed.' >&2
    exit 1
fi
if bash "$metadata_script" 1.2.3 2026.07.3.0 stable; then
    echo 'An invalid tModLoader tag unexpectedly passed.' >&2
    exit 1
fi

GITHUB_REPOSITORY=Crosis47/tmodloader \
GITHUB_SHA=0123456789abcdef \
    bash "$notes_script" \
        "$current_version" \
        v2026.07.3.0 \
        stable \
        ghcr.io/crosis47/tmodloader \
        sha256:abcdef \
        "${current_version}-tml-v2026-07-3-0-stable" \
        tml-v2026.07.3.0-stable \
        true \
        > "$notes_output"

grep -Fq '## Container changelog' "$notes_output"
grep -Fq "ghcr.io/crosis47/tmodloader:${current_version}-tml-v2026-07-3-0-stable" "$notes_output"
grep -Fq 'ghcr.io/crosis47/tmodloader@sha256:abcdef' "$notes_output"
grep -Fq 'tModLoader v2026.07.3.0 release notes' "$notes_output"
grep -Fq 'Moving channel tag(s): `latest` and `stable`' "$notes_output"

GITHUB_REPOSITORY=Crosis47/tmodloader \
GITHUB_SHA=0123456789abcdef \
    bash "$notes_script" \
        "$current_version" \
        v2026.07.3.0 \
        stable \
        ghcr.io/crosis47/tmodloader \
        sha256:abcdef \
        "${current_version}-tml-v2026-07-3-0-stable" \
        tml-v2026.07.3.0-stable \
        false \
        > "$manual_notes_output"
grep -Fq 'Moving channel tag(s): not moved by this manual build' "$manual_notes_output"

echo 'release metadata tests passed.'
