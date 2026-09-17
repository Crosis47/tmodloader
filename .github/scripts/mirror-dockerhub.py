"""Mirror completed releases, preserving exact manifests and numbered tags."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def run(*args):
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def manifest(reference, missing_ok=False):
    try:
        raw = run("docker", "buildx", "imagetools", "inspect", "--raw", reference)
    except subprocess.CalledProcessError as error:
        # Authentication, rate limits, and transport errors must never mean absent.
        message = error.stderr.decode(errors="replace").lower()
        if missing_ok and ("manifest unknown" in message or "not found" in message):
            return None
        raise
    return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(raw)


def mirror(repository, source, target, tag, channel):
    release = json.loads(run("gh", "release", "view", tag, "--repo", repository,
                             "--json", "body,isDraft"))
    if release["isDraft"]:
        raise ValueError(f"Refusing draft release {tag}")
    notes = release["body"]
    digests = set(re.findall(re.escape(source) + r"@(sha256:[0-9a-f]{64})", notes))
    if len(digests) != 1:
        raise ValueError(f"Release {tag} must identify exactly one tested source digest")
    digest = digests.pop()
    actual, index = manifest(f"{source}:{tag}")
    if actual != digest:
        raise ValueError(f"Source tag {tag} differs from its release digest")
    platforms = {(item.get("platform", {}).get("os"),
                  item.get("platform", {}).get("architecture"))
                 for item in index.get("manifests", [])}
    if not {("linux", "amd64"), ("linux", "arm64")} <= platforms:
        raise ValueError(f"Source {tag} is missing AMD64 or ARM64")
    existing = manifest(f"{target}:{tag}", missing_ok=True)
    if existing and existing[0] != digest:
        raise ValueError(f"Refusing to replace numbered Docker Hub tag {tag}")
    tags = [tag]
    # A retry of an older release must not roll moving aliases backward.
    for alias in (["latest"] if channel == "stable" else ["preview"]):
        current = manifest(f"{source}:{alias}", missing_ok=True)
        if current and current[0] == digest:
            tags.append(alias)
    args = ["docker", "buildx", "imagetools", "create"]
    for name in tags:
        args.extend(["--tag", f"{target}:{name}"])
    run(*args, f"{source}@{digest}")
    for name in tags:
        if manifest(f"{target}:{name}")[0] != digest:
            raise ValueError(f"Docker Hub verification failed for {name}")
    # Preserve the original changelog, source commit, and validation evidence.
    marker = f"<!-- dockerhub:{target}:{tag} -->"
    if marker not in notes:
        notes += (f"\n\n{marker}\n### Docker Hub\n\n"
                  f"```bash\ndocker pull {target}:{tag}\n```\n\n"
                  f"Verified multi-platform digest: `{target}@{digest}`\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text(notes, encoding="utf-8")
            run("gh", "release", "edit", tag, "--repo", repository,
                "--notes-file", str(path))
    print(f"Verified {target}:{tag} ({digest}); tags: {', '.join(tags)}")


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    target = os.environ["DOCKERHUB_IMAGE"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_.-]*", target):
        raise ValueError("DOCKERHUB_IMAGE must be a lowercase namespace/repository")
    version = Path("VERSION").read_text().strip()
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Invalid VERSION")
    source = f"ghcr.io/{repository.split('/')[0].lower()}/tmodloader"
    # List releases so an absent preview is distinct from a failed registry request.
    releases = json.loads(run("gh", "release", "list", "--repo", repository,
                              "--limit", "1000", "--json", "tagName,isDraft"))
    available = {item["tagName"] for item in releases if not item["isDraft"]}
    if version not in available:
        raise ValueError(f"Stable release {version} must be published first")
    mirror(repository, source, target, version, "stable")
    if f"{version}-preview" in available:
        mirror(repository, source, target, f"{version}-preview", "preview")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr.decode(errors="replace"), file=sys.stderr)
        raise SystemExit(error.returncode) from error
