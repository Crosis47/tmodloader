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

grep -Fxq 'release_tag=1.2.3' "$metadata_output"
grep -Fxq 'docker_tag=1.2.3' "$metadata_output"
grep -Fxq 'prerelease=false' "$metadata_output"

GITHUB_OUTPUT="$preview_metadata_output" \
    bash "$metadata_script" 1.2.3 v2026.08.2.1 preview
grep -Fxq 'release_tag=1.2.3-preview' "$preview_metadata_output"
grep -Fxq 'docker_tag=1.2.3-preview' "$preview_metadata_output"
grep -Fxq 'prerelease=true' "$preview_metadata_output"

docker_tag="$(sed -n 's/^docker_tag=//p' "$metadata_output")"
if ! [[ "$docker_tag" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$ ]]; then
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
        "${current_version}" \
        true \
        > "$notes_output"

grep -Eq "^## \[${current_version//./\\.}\].* - [0-9]{4}-[0-9]{2}-[0-9]{2}$" "$notes_output"
grep -Eq '^### (Added|Changed|Deprecated|Removed|Fixed|Security)$' "$notes_output"
grep -Fxq '<details>' "$notes_output"
grep -Fxq '</details>' "$notes_output"
grep -Fq "ghcr.io/crosis47/tmodloader:${current_version}" "$notes_output"
grep -Fq 'ghcr.io/crosis47/tmodloader@sha256:abcdef' "$notes_output"
grep -Fq 'tModLoader v2026.07.3.0 release notes' "$notes_output"
grep -Fq 'Moving channel tag(s): `latest`' "$notes_output"

GITHUB_REPOSITORY=Crosis47/tmodloader \
GITHUB_SHA=0123456789abcdef \
    bash "$notes_script" \
        "$current_version" \
        v2026.07.3.0 \
        stable \
        ghcr.io/crosis47/tmodloader \
        sha256:abcdef \
        "${current_version}" \
        false \
        > "$manual_notes_output"
grep -Fq 'Moving channel tag(s): not moved by this manual build' "$manual_notes_output"

bash "$notes_script" "$current_version" v2026.08.2.1 preview \
    ghcr.io/crosis47/tmodloader sha256:abcdef "${current_version}-preview" true \
    > "$test_root/preview-notes.md"
grep -Fq "GitHub Release tag: \`${current_version}-preview\`" "$test_root/preview-notes.md"
grep -Fq 'Moving channel tag(s): `preview`' "$test_root/preview-notes.md"
if grep -Eq 'lookup tag:|Compatibility tag:|-tml-' "$notes_output" "$test_root/preview-notes.md"; then
    echo 'Release notes advertised an obsolete image tag.' >&2
    exit 1
fi

# Accept linked Keep a Changelog headings and historical plain headings,
# extracting only the exact version and excluding reference definitions.
for heading in '[1.2.3]' '1.2.3'; do
    cat > "$test_root/changelog.md" <<EOF
## [Unreleased]
### Added
- unreleased-only
## [1.2.30] - 2026-09-17
### Fixed
- other-version-only
## $heading - 2026-09-16
### Fixed
- selected-fix

[1.2.3]: https://example.invalid/compare
EOF
    CONTAINER_CHANGELOG_PATH="$test_root/changelog.md" bash "$notes_script" \
        1.2.3 v2026.07.3.0 stable example/image sha256:abc 1.2.3 true > "$test_root/selected.md"
    grep -Fxq -- '- selected-fix' "$test_root/selected.md"
    grep -q '^## .* - 2026-09-16$' "$test_root/selected.md"
    if grep -Eq 'unreleased-only|other-version-only|example.invalid' "$test_root/selected.md"; then
        echo 'Release notes included unrelated changelog content.' >&2
        exit 1
    fi
done
if CONTAINER_CHANGELOG_PATH="$test_root/changelog.md" bash "$notes_script" \
    9.9.9 v2026.07.3.0 stable example/image sha256:abc 9.9.9 true; then
    echo 'Missing changelog version unexpectedly passed.' >&2
    exit 1
fi
printf '## [1.2.3]\n### Fixed\n- Missing date\n' > "$test_root/changelog.md"
if CONTAINER_CHANGELOG_PATH="$test_root/changelog.md" bash "$notes_script" \
    1.2.3 v2026.07.3.0 stable example/image sha256:abc 1.2.3 true; then
    echo 'Missing release date unexpectedly passed.' >&2
    exit 1
fi

echo 'release metadata tests passed.'
