# Docker Hub publishing

The existing **Publish tModLoader images and releases** Action can mirror its
verified GHCR releases to Docker Hub. It copies the complete multi-platform image
index, including AMD64, ARM64, provenance, and SBOM manifests; no rebuild is needed.

## One-time setup

1. Create the public Docker Hub repository `crosis47/tmodloader`.
2. Create a Docker Hub personal access token with Read and Write access.
3. In this GitHub repository, open **Settings → Secrets and variables → Actions**:
   - Variable `DOCKERHUB_USERNAME`: `crosis47`
   - Variable `DOCKERHUB_IMAGE`: `crosis47/tmodloader`
   - Secret `DOCKERHUB_TOKEN`: the access token

Never place the token in source files, variables, or release notes. Leaving
`DOCKERHUB_IMAGE` unset disables the mirror job and keeps GHCR publishing working.
When enabled, missing or invalid credentials fail the mirror job visibly.

## Publish or retry

New releases are built and tested through the existing workflow, published to
GHCR, and recorded as GitHub Releases before the Docker Hub job runs. Successful
copies add a Docker Hub pull command to the existing release notes.

To copy the current release immediately or recover a failed Docker Hub upload,
run the publishing workflow manually with **mirror_only** selected. This copies
the stable release named in `VERSION` and its preview release if present, without
resolving new upstream versions or building an image. It requires a completed
GitHub Release and a matching GHCR image. The workflow change must be on the
selected branch; merge it into `master` for scheduled and normal release runs.

The mirror verifies the release-note digest against the GHCR numbered tag, then
verifies every copied Docker Hub tag against the same digest. An existing numbered
Docker Hub tag with different contents causes failure. Moving aliases (`latest`,
`stable`, `preview`) are copied only when the GHCR alias still points at that
release, so retrying an older release cannot roll those aliases back.

A Docker Hub failure leaves the completed GHCR release intact. Fix the reported
problem and rerun with **mirror_only**. This mode does not repair an incomplete
GHCR publication and does not backfill the entire release history.

After the first successful copy:

```bash
docker pull crosis47/tmodloader:latest
```

Both registries use the same version tags and multi-platform digest. Existing
Compose deployments can continue using GHCR.
