"""Render the Docker Hub overview from the README and published release notes."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen


def absolute_links(markdown, repository):
    """Convert repository links, including linked gallery images, outside fences."""
    def replace(match):
        target = match[0]
        if target.startswith(("#", "//")) or urlsplit(target).scheme:
            return target
        image = Path(urlsplit(target).path).suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
        base = (f"https://raw.githubusercontent.com/{repository}/master/" if image
                else f"https://github.com/{repository}/blob/master/")
        return urljoin(base, target)

    lines = []
    fence = None
    for line in markdown.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            lines.append(line)
        elif fence:
            lines.append(line)
        else:
            lines.append(re.sub(r"(?<=\]\()[^\s)]+(?=\))", replace, line))
    return "".join(lines)


def render(readme, release, repository):
    if release["isDraft"] or release["isPrerelease"]:
        raise ValueError("Overview requires a published stable release")
    # Our release notes lead with the versioned changelog and put build details
    # in <details>. Do not advertise the checkout's Unreleased changes as shipped.
    changes = release["body"].split("<details>", 1)[0].strip()
    if not changes:
        raise ValueError("Published release notes are empty")
    section = (f"\n\n## Latest release changes\n\n{changes}\n\n"
               f"[Full changelog](https://github.com/{repository}/blob/master/CHANGELOG.md)"
               f" · [All releases and preview notes](https://github.com/{repository}/releases)\n")
    # Keep the README intact, with changes below the introductory description.
    position = readme.find("\n## ")
    if position < 0:
        position = len(readme)
    result = absolute_links(readme[:position] + section + readme[position:], repository)
    if len(result.encode("utf-8")) > 25000:
        raise ValueError("Docker Hub overview exceeds 25,000 bytes; shorten the README or release notes")
    return result


def verify(path, image):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_.-]*", image):
        raise ValueError("Invalid Docker Hub image name")
    with urlopen(f"https://hub.docker.com/v2/repositories/{image}/", timeout=30) as response:
        actual = json.load(response)["full_description"]
    expected = Path(path).read_text(encoding="utf-8")
    if actual.replace("\r\n", "\n").strip() != expected.strip():
        raise ValueError("Docker Hub Overview does not match the generated content")
    print(f"Verified README and published release notes on Docker Hub: {image}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--verify", metavar="IMAGE")
    args = parser.parse_args()
    if args.verify:
        verify(args.output, args.verify)
        return
    repository = os.environ["GITHUB_REPOSITORY"]
    release = json.loads(subprocess.check_output([
        "gh", "release", "view", "--repo", repository,
        "--json", "body,tagName,isDraft,isPrerelease"]))
    content = render(Path("README.md").read_text(encoding="utf-8"), release, repository)
    Path(args.output).write_text(content, encoding="utf-8")
    print(f"Rendered README and {release['tagName']} changes ({len(content.encode('utf-8'))} bytes)")


if __name__ == "__main__":
    main()
