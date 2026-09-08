# Security Policy

## Project scope

This repository is an independently maintained hard fork of
`JACOBSMILE/tmodloader1.4`. Security reports for this repository should concern
the Dockerfile, container entrypoint and helper scripts, GitHub Actions
workflows, published GHCR images, or the way those pieces integrate tModLoader.

Vulnerabilities in tModLoader, Terraria, SteamCMD, or another bundled upstream
component should normally be reported to that component's maintainers. If the
container makes an upstream issue exploitable in a new way, please report it
here as well.

## Supported images

Security fixes are applied to images built from the current `master` branch.
The release workflows refuse to reuse exact composite container/tModLoader
tags. The `latest`, `stable`, `preview`, tModLoader lookup, and legacy
upstream-only compatibility aliases can move as the container changes. Pin an
image digest when an immutable deployment is needed. Older image digests do not
receive in-place updates.

## Reporting a vulnerability

GitHub private vulnerability reporting is not currently enabled for this
repository. Open a minimal public issue that asks the maintainer to establish a
private contact channel. Do **not** include exploit details, secrets, private
server data, or other information that would make the vulnerability easier to
abuse. Once a private channel is available, provide the complete report there.

Include as much of the following as possible:

- The affected image tag and digest.
- The affected file, command, or configuration.
- Reproduction steps and the expected impact.
- Whether the issue is reachable over the network or requires host access.
- A proposed mitigation or patch, if one is available.

Remove passwords, tokens, world data, player addresses, and other private data
from logs before attaching them. There is no guaranteed response-time SLA, but
reports will be reviewed as maintainer availability permits. Please allow time
for a fix and rebuilt image before public disclosure.

## Deployment security guidance

- Set a unique server password, preferably through `TMOD_PASS_FILE`.
- Publish only the configured Terraria TCP port. Never mount the Docker socket
  or unrelated host directories into this container.
- Keep `/data` writable only by trusted host users and include it in backups.
- The container currently runs as root for SteamCMD and tModLoader
  compatibility. Treat any mounted path as accessible to the container.
- Keep Docker, the host operating system, and the deployed image updated.
- Use an image digest when deployment policy requires a reviewed, immutable
  artifact.
