#!/usr/bin/env bash

set -Eeuo pipefail

if (($# != 7)); then
    printf 'Usage: %s CONTAINER_VERSION TMODLOADER_VERSION CHANNEL IMAGE DIGEST DOCKER_TAG UPDATE_CHANNEL_ALIASES\n' "$0" >&2
    exit 2
fi

container_version="$1"
tml_version="$2"
channel="$3"
image="$4"
digest="$5"
docker_tag="$6"
update_channel_aliases="$7"
changelog_path="${CONTAINER_CHANGELOG_PATH:-CHANGELOG.md}"
repository="${GITHUB_REPOSITORY:-Crosis47/tmodloader}"
commit="${GITHUB_SHA:-local}"
github_release_tag="$docker_tag"

case "$channel" in
    stable|preview) ;;
    *)
        printf '[!!] Channel must be stable or preview: %s\n' "$channel" >&2
        exit 1
        ;;
esac
case "$update_channel_aliases" in
    true|false) ;;
    *)
        printf '[!!] UPDATE_CHANNEL_ALIASES must be true or false.\n' >&2
        exit 1
        ;;
esac

[[ -s "$changelog_path" ]] || {
    printf '[!!] Changelog not found: %s\n' "$changelog_path" >&2
    exit 1
}

section="$(awk -v version="$container_version" '
    { sub(/\r$/, "") }
    /^## / {
        if (capture) {
            exit
        }
        if ($2 == version || $2 == "[" version "]") {
            capture = 1
            print
        }
        next
    }
    capture && !/^\[[^]]+\]:/ { print }
' "$changelog_path")"
release_date="$(head -n 1 <<< "$section" | awk '{print $4}')"
changes="$(tail -n +2 <<< "$section")"

if ! grep -q '[^[:space:]]' <<< "$changes"; then
    printf '[!!] CHANGELOG.md has no section for container version %s.\n' "$container_version" >&2
    exit 1
fi

if ! [[ "$release_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    printf '[!!] Changelog release %s requires an ISO date (YYYY-MM-DD).\n' "$container_version" >&2
    exit 1
fi

if [[ "$update_channel_aliases" != "true" ]]; then
    channel_tags="not moved by this manual build"
elif [[ "$channel" == "stable" ]]; then
    channel_tags="\`latest\`"
else
    channel_tags="\`preview\`"
fi

printf '## [%s](https://github.com/%s/releases/tag/%s) - %s\n%s\n\n' \
    "$github_release_tag" "$repository" "$github_release_tag" "$release_date" "$changes"
printf '<details>\n<summary>Images, validation, and source</summary>\n\n'
printf 'This release packages container **v%s** with **tModLoader %s** on the **%s** channel.\n\n' \
    "$container_version" "$tml_version" "$channel"
printf '### Published images\n\n'
printf -- '- GitHub Release tag: `%s`\n' "$github_release_tag"
printf -- '- Version tag: `%s:%s`\n' "$image" "$docker_tag"
printf -- '- Moving channel tag(s): %s\n' "$channel_tags"
printf -- '- Immutable tested digest: `%s@%s`\n\n' "$image" "$digest"
printf '```bash\ndocker pull %s:%s\n```\n\n' "$image" "$docker_tag"
printf '### Validation\n\n'
printf 'The candidate digest passed Bash and configuration regression tests, '
printf 'a real dedicated-server startup and healthcheck, command injection, '
printf 'graceful shutdown, password-leak detection, and persistent-log verification '
printf 'on both linux/amd64 and linux/arm64 before these tags were assigned.\n\n'
printf 'Native executable architecture and live Workshop download/cache reuse were also verified.\n\n'
printf '### Upstream and source\n\n'
printf -- '- [tModLoader %s release notes](https://github.com/tModLoader/tModLoader/releases/tag/%s)\n' \
    "$tml_version" "$tml_version"
printf -- '- [Container source at %s](https://github.com/%s/tree/%s)\n' \
    "$commit" "$repository" "$commit"
printf '\n</details>\n'
