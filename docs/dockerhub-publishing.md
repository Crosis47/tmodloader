# Docker Hub publishing

The existing **Publish container releases** Action can mirror its
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
selected branch; merge it into `master` for version-triggered release runs.

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

## README and release notes

The **Sync Docker Hub overview** Action publishes the full README plus the latest
published stable release's changelog section to Docker Hub's Overview. It links
to the full changelog and all stable/preview release notes. Relative screenshot
and document links become absolute URLs so they work on Docker Hub. Unreleased
changelog entries are not presented as shipped changes.

The image publisher calls this workflow after successful copying, including
mirror-only retries. It also runs on README/changelog edits on `master`, on
published/edited GitHub Releases, and manually. Documentation edits do not need
a container rebuild. The uploaded content is read back and verified; content
over Docker Hub's 25,000-byte limit fails visibly instead of being truncated.

This uses the existing `DOCKERHUB_TOKEN`. The Docker Hub description action
documents a personal access token with **Read, Write, Delete** permission for
repository metadata updates. If the existing image-push token is rejected,
replace that GitHub secret with an appropriately permitted token. No images
are deleted by this workflow.

Docker Hub's built-in README auto-import applies to its own automated builds;
this repository uses GitHub Actions, so the Overview is synced explicitly.

When README content and published release notes exceed Docker Hub's 25,000-byte limit, the renderer replaces detailed reference sections with links to the full README. Setup instructions and published release changes stay intact; Markdown is never cut mid-section. Shorter overviews retain the complete README.
