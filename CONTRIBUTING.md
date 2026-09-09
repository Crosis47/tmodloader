# Contributing

Thank you for helping maintain this tModLoader container. Contributions should
focus on container behavior, deployment, Workshop management, automation,
documentation, or fixes that make the dedicated server more reliable.

This project is a hard fork of `JACOBSMILE/tmodloader1.4`; new work should be
submitted here rather than assuming it will be accepted by or synchronized
with the original repository.

## Before starting

- Search existing issues and pull requests for related work.
- Use a normal issue for bugs and feature requests.
- Use the private process in [SECURITY.md](SECURITY.md) for vulnerabilities.
- Discuss large behavior or compatibility changes before implementing them.

## Development environment

Install Git, Docker Engine or Docker Desktop, and Bash. ShellCheck and
actionlint are recommended; both can also be run from containers. On Windows,
Git Bash is the simplest way to run the repository's Bash tests.

Create a branch from the current `master`, make focused changes, and preserve
backward compatibility unless the pull request clearly documents a necessary
breaking change.

## Required validation

Backup tooling requires Python 3.12+. Run `python3 -m unittest discover -s tests
-p 'test_backup.py' -v`. On a local Linux Docker host, also run
`sudo python3 tests/backup-integration-test.py tmodloader:dev` after building the
image. This creates disposable data and checks an actual server backup/restore
cycle with ownership and health verification.

Run the checks relevant to your change. Runtime changes should pass the full
set:

```bash
bash -n ./*.sh tests/*.sh
shellcheck --severity=warning autosave.sh entrypoint.sh healthcheck.sh inject.sh \
  log-filter.sh manage-mods.sh prepare-config.sh run-server.sh tests/*.sh
docker compose config --quiet
docker build --tag tmodloader:dev .
```

Run the script tests against the built image:

```bash
docker run --rm --entrypoint bash \
  --mount type=bind,source="$PWD",target=/repo,readonly \
  tmodloader:dev \
  /repo/tests/manage-mods-test.sh /terraria-server/manage-mods.sh

docker run --rm --entrypoint bash \
  --mount type=bind,source="$PWD",target=/repo,readonly \
  tmodloader:dev \
  /repo/tests/locale-test.sh /usr/bin/steamcmd

docker run --rm --entrypoint bash \
  --mount type=bind,source="$PWD",target=/repo,readonly \
  tmodloader:dev \
  /repo/tests/config-test.sh /terraria-server/prepare-config.sh

docker run --rm --entrypoint bash \
  --mount type=bind,source="$PWD",target=/repo,readonly \
  tmodloader:dev \
  /repo/tests/log-filter-test.sh /terraria-server/log-filter.sh /terraria-server/run-server.sh

docker run --rm --entrypoint bash \
  --mount type=bind,source="$PWD",target=/repo,readonly \
  tmodloader:dev \
  /repo/tests/runtime-control-test.sh /usr/local/bin/inject

bash tests/server-smoke-test.sh tmodloader:dev
```

The smoke test creates temporary Docker resources, starts a real tModLoader
server, verifies health and command injection, stops it, checks the exit status,
verifies the non-root identity and hardened runtime, and verifies persistent
logs. It can take several minutes on an uncached host.

When invoking bind mounts from PowerShell, replace `$PWD` with an absolute
Windows path. GitHub Actions runs the same build and runtime checks on pull
requests.

## Change guidelines

- Use `set -Eeuo pipefail` in Bash scripts unless a documented compatibility
  reason prevents it.
- Quote expansions and keep ShellCheck clean at warning severity.
- Validate user-controlled values before writing config files or commands.
- Never print passwords, tokens, or other secrets.
- Add regression coverage for fixed bugs and failure paths.
- Keep network-dependent tests out of the script test suite; use deterministic
  mocks there and reserve network/server behavior for the Docker smoke test.
- Update `README.md`, `.env.example`, and `CHANGELOG.md` when behavior or
  configuration changes.

## Versioning and changelog

`VERSION` contains the container's `MAJOR.MINOR.PATCH` SemVer core:

- Increment `MAJOR` for incompatible configuration, data-layout, or operational
  changes.
- Increment `MINOR` for backward-compatible container features.
- Increment `PATCH` for backward-compatible fixes and security updates.

A newly discovered tModLoader release does not require a container version bump
when the container contract is unchanged; its version is recorded separately in
the composite release tag. Before merging a container change that should publish
a release, increment `VERSION`, add a matching `## X.Y.Z - YYYY-MM-DD` section
to `CHANGELOG.md`, and return `## Unreleased` to an empty state. The release
workflow refuses to reuse an existing composite release tag.

## Pull requests and publishing

Use an imperative commit subject and explain the user-visible result, risks,
compatibility impact, and validation in the pull request. Do not manually move
public image tags as part of a contribution. After changes reach `master`, the
publisher builds and tests an untagged candidate digest before updating GHCR
tags. It then creates a GitHub Release from the matching versioned changelog
section. The automation refuses to reuse exact composite tags; only documented
channel and compatibility aliases move.
