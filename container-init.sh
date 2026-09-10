#!/bin/bash

set -Eeuo pipefail

runtime_user="tml"
runtime_group="tml"

fail() {
    printf '[!!] FATAL: %s\n' "$*" >&2
    exit 1
}

repair_tree() {
    local path="$1"
    local repair_failed=0

    mkdir -p -- "$path" || fail "Cannot create required persistent directory: $path"
    printf '[INIT] Repairing ownership and directory access under %s.\n' "$path"

    # Do not follow symlinks or descend into nested filesystems. Changing only
    # mismatched entries avoids rewriting metadata across a large Workshop tree
    # on every container start.
    if ! find "$path" -xdev \( ! -user "$runtime_user" -o ! -group "$runtime_group" \) \
        -exec chown --no-dereference "$runtime_user:$runtime_group" {} +; then
        repair_failed=1
    fi
    if ! find "$path" -xdev -type d ! -perm -0700 -exec chmod u+rwx {} +; then
        repair_failed=1
    fi

    if ((repair_failed)); then
        printf '[INIT] WARNING: Could not fully repair %s; runtime access checks will verify the result.\n' "$path" >&2
    fi
}

[[ "$(id -u)" == "0" ]] || fail "Container initialization must start as root so mounted-directory permissions can be repaired."
[[ -x /usr/bin/setpriv ]] || fail "setpriv is required to drop runtime privileges."
getent passwd "$runtime_user" >/dev/null || fail "Runtime user does not exist: $runtime_user"
getent group "$runtime_group" >/dev/null || fail "Runtime group does not exist: $runtime_group"

repair_tree /data
repair_tree /backups

runtime_uid="$(id -u "$runtime_user")"
runtime_gid="$(id -g "$runtime_user")"
printf '[INIT] Dropping privileges to %s (uid=%s gid=%s).\n' "$runtime_user" "$runtime_uid" "$runtime_gid"

exec /usr/bin/setpriv \
    --reuid="$runtime_user" \
    --regid="$runtime_group" \
    --init-groups \
    --no-new-privs \
    -- "$@"
