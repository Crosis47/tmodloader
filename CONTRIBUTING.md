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

Run the checks relevant to your change. Runtime changes should pass the full
set:

```bash
bash -n ./*.sh tests/*.sh
shellcheck --severity=warning autosave.sh entrypoint.sh healthcheck.sh inject.sh \
  manage-mods.sh prepare-config.sh run-server.sh tests/*.sh
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
  /repo/tests/config-test.sh /terraria-server/prepare-config.sh

bash tests/server-smoke-test.sh tmodloader:dev
```

The smoke test creates temporary Docker resources, starts a real tModLoader
server, verifies health and command injection, stops it, checks the exit status,
and verifies persistent logs. It can take several minutes on an uncached host.

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

## Pull requests and publishing

Use an imperative commit subject and explain the user-visible result, risks,
compatibility impact, and validation in the pull request. Do not manually move
public image tags as part of a contribution. After changes reach `master`, the
publisher builds and tests an untagged candidate digest before updating GHCR
tags.
