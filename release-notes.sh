#!/usr/bin/env bash

set -Eeuo pipefail

if (($# != 8)); then
    printf 'Usage: %s CONTAINER_VERSION TMODLOADER_VERSION CHANNEL IMAGE DIGEST DOCKER_TAG TMOD_TAG UPDATE_CHANNEL_ALIASES\n' "$0" >&2
    exit 2
fi

container_version="$1"
tml_version="$2"
channel="$3"
image="$4"
digest="$5"
docker_tag="$6"
tml_tag="$7"
update_channel_aliases="$8"
changelog_path="${CONTAINER_CHANGELOG_PATH:-CHANGELOG.md}"
repository="${GITHUB_REPOSITORY:-Crosis47/tmodloader}"
commit="${GITHUB_SHA:-local}"
github_release_tag="${container_version}+tml.${tml_version}.${channel}"

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

changes="$(awk -v version="$container_version" '
    /^## / {
        if (capture) {
            exit
        }
        prefix = "## " version
        if (index($0, prefix) == 1) {
            remainder = substr($0, length(prefix) + 1, 1)
            if (remainder == "" || remainder == " ") {
                capture = 1
            }
        }
        next
    }
    capture { print }
' "$changelog_path")"

if ! grep -q '[^[:space:]]' <<< "$changes"; then
    printf '[!!] CHANGELOG.md has no section for container version %s.\n' "$container_version" >&2
    exit 1
fi

if [[ "$update_channel_aliases" != "true" ]]; then
    channel_tags="not moved by this manual build"
elif [[ "$channel" == "stable" ]]; then
    channel_tags="\`latest\` and \`stable\`"
else
    channel_tags="\`preview\`"
fi

printf 'This release packages container **v%s** with **tModLoader %s** on the **%s** channel.\n\n' \
    "$container_version" "$tml_version" "$channel"
printf '## Container changelog\n%s\n\n' "$changes"
printf '## Published images\n\n'
printf -- '- GitHub Release tag: `%s`\n' "$github_release_tag"
printf -- '- Exact container/tModLoader tag: `%s:%s`\n' "$image" "$docker_tag"
printf -- '- tModLoader lookup tag: `%s:%s`\n' "$image" "$tml_tag"
printf -- '- Compatibility tag: `%s:%s`\n' "$image" "$tml_version"
printf -- '- Moving channel tag(s): %s\n' "$channel_tags"
printf -- '- Immutable tested digest: `%s@%s`\n\n' "$image" "$digest"
printf '```bash\ndocker pull %s:%s\n```\n\n' "$image" "$docker_tag"
printf '## Validation\n\n'
printf 'The candidate digest passed Bash and configuration regression tests, '
printf 'a real dedicated-server startup and healthcheck, command injection, '
printf 'graceful shutdown, password-leak detection, and persistent-log verification '
printf 'before these tags were assigned.\n\n'
printf '## Upstream and source\n\n'
printf -- '- [tModLoader %s release notes](https://github.com/tModLoader/tModLoader/releases/tag/%s)\n' \
    "$tml_version" "$tml_version"
printf -- '- [Container source at %s](https://github.com/%s/tree/%s)\n' \
    "$commit" "$repository" "$commit"
