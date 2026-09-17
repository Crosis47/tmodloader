"""Collect public counters and generate content-addressed README badges."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess

START = "<!-- repository-stats:start -->"
END = "<!-- repository-stats:end -->"


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid counter: {value!r}")
    return value


class PackageStats(HTMLParser):
    def __init__(self):
        super().__init__()
        self.total = None
        self.want_total = False
        self.depth = 0
        self.chart_depth = None
        self.days = {}

    def handle_data(self, text):
        if text.strip() == "Total downloads":
            self.want_total = True

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.depth += 1
            if attrs.get("aria-label") == "Downloads for the last 30 days":
                self.chart_depth = self.depth
        if tag == "h3" and self.want_total and "title" in attrs:
            self.total = count(int(attrs["title"].replace(",", "")))
            self.want_total = False
        if tag == "rect" and self.chart_depth is not None:
            day = date.fromisoformat(attrs["data-date"])
            if day in self.days:
                raise ValueError("Duplicate GHCR chart date")
            self.days[day] = count(int(attrs["data-merge-count"]))

    def handle_endtag(self, tag):
        if tag == "div":
            if self.depth == self.chart_depth:
                self.chart_depth = None
            self.depth -= 1


def package_counts(html, today):
    parser = PackageStats()
    parser.feed(html)
    if parser.total is None or not parser.days:
        raise ValueError("GHCR download counters were not found; page markup may have changed")
    if max(parser.days) not in (today, today - timedelta(days=1)):
        raise ValueError("GHCR daily chart is stale or dated in the future")
    # Use dates rather than DOM order; includes the current partial UTC day.
    end = max(parser.days)
    days = [end - timedelta(days=i) for i in range(7)]
    if not all(day in parser.days for day in days):
        raise ValueError("GHCR chart is missing dates in its seven-day window")
    return {"ghcr_pulls": parser.total,
            "ghcr_day": parser.days[end],
            "ghcr_week": sum(parser.days[day] for day in days),
            "ghcr_week_start": str(days[-1]), "ghcr_week_end": str(end)}


def public_text(url):
    return subprocess.check_output([
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "2", "--max-time", "30", url], encoding="utf-8")


def github_json(*args):
    return json.loads(subprocess.check_output(["gh", "api", *args], encoding="utf-8"))


def collect(repository, image):
    docker = json.loads(public_text(f"https://hub.docker.com/v2/repositories/{image}/"))
    repo = github_json(f"repos/{repository}")
    metrics = {"docker_pulls": count(docker["pull_count"]),
               "docker_stars": count(docker["star_count"]),
               "github_stars": count(repo["stargazers_count"]),
               "github_forks": count(repo["forks_count"])}
    for key, query in {"issues_open": "is:issue is:open", "issues_closed": "is:issue is:closed",
                       "prs_open": "is:pr is:open", "prs_merged": "is:pr is:merged"}.items():
        result = github_json("search/issues", "--method", "GET", "-f",
                             f"q=repo:{repository} {query}", "-f", "per_page=1")
        if result.get("incomplete_results"):
            raise ValueError("GitHub returned incomplete issue/PR search results")
        metrics[key] = count(result["total_count"])
    owner = repository.split("/")[0]
    package = image.split("/")[1]
    metrics.update(package_counts(public_text(
        f"https://github.com/{repository}/pkgs/container/{package}"),
        datetime.now(timezone.utc).date()))
    return {"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "repository": repository, "docker_image": image,
            "ghcr_image": f"ghcr.io/{owner.lower()}/{package}", "metrics": metrics}


def badge(label, value, color):
    value = f"{count(value):,}"
    label = label.upper()
    left, right = len(label) * 7 + 22, len(value) * 8 + 22
    total = left + right
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="28" '
            f'role="img" aria-label="{escape(label)}: {value}">'
            f'<title>{escape(label)}: {value}</title>'
            f'<path fill="#344253" d="M0 0h{left}v28H0z"/>'
            f'<path fill="#{color}" d="M{left} 0h{right}v28H{left}z"/>'
            '<g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" '
            'font-size="11" font-weight="bold">'
            f'<text x="{left / 2}" y="18">{escape(label)}</text>'
            f'<text x="{left + right / 2}" y="18">{value}</text></g></svg>\n')


def write_snapshot(root, snapshot):
    repository, image, metrics = snapshot["repository"], snapshot["docker_image"], snapshot["metrics"]
    github = f"https://github.com/{repository}"
    hub = f"https://hub.docker.com/r/{image}"
    specs = [
        ("docker_pulls", "Docker pulls", hub, "087CA7"),
        ("docker_stars", "Docker stars", hub, "087CA7"),
        ("ghcr_pulls", "GHCR pulls", github + "/pkgs/container/" + image.split('/')[1], "6554C0"),
        ("ghcr_week", "GHCR pulls / 7d", github + "/pkgs/container/" + image.split('/')[1], "6554C0"),
        ("ghcr_day", "GHCR pulls today", github + "/pkgs/container/" + image.split('/')[1], "6554C0"),
        ("github_stars", "GitHub stars", github + "/stargazers", "786312"),
        ("github_forks", "GitHub forks", github + "/forks", "536471"),
        ("issues_open", "Issues open", github + "/issues?q=is%3Aissue+is%3Aopen", "22863A"),
        ("issues_closed", "Issues closed", github + "/issues?q=is%3Aissue+is%3Aclosed", "6554C0"),
        ("prs_open", "PRs open", github + "/pulls", "22863A"),
        ("prs_merged", "PRs merged", github + "/pulls?q=is%3Apr+is%3Amerged", "6554C0"),
    ]
    readme = root / "README.md"
    original = readme.read_text(encoding="utf-8")
    if original.count(START) != 1 or original.count(END) != 1 or original.index(END) < original.index(START):
        raise ValueError("README must contain exactly one ordered statistics marker pair")
    files, lines = {}, [START]
    for key, label, link, color in specs:
        svg = badge(label, metrics[key], color)
        digest = hashlib.sha256(svg.encode()).hexdigest()[:16]
        name = f"{key}-{digest}.svg"
        files[name] = svg
        url = f"https://raw.githubusercontent.com/{repository}/master/docs/stats/badges/{name}"
        lines.append(f"[![{label}]({url})]({link})")
        if key in ("ghcr_week", "github_forks"):
            lines.append("")
    lines.extend(["", f"Updated **{snapshot['updated_at']}** · Refreshed hourly · "
                  "[Metric definitions](docs/repository-stats.md)", END])
    block = "\n".join(lines)
    updated = original[:original.index(START)] + block + original[original.index(END) + len(END):]
    directory = root / "docs/stats/badges"
    directory.mkdir(parents=True, exist_ok=True)
    for name, svg in files.items():
        (directory / name).write_text(svg, encoding="utf-8")
    # Retain old content-addressed assets so cached/historical README links work.
    (directory.parent / "latest.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    readme.write_text(updated, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", help="Render an already collected JSON snapshot")
    args = parser.parse_args()
    if args.snapshot:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8-sig"))
    else:
        repository = os.environ["GITHUB_REPOSITORY"]
        image = os.environ.get("DOCKERHUB_IMAGE", "crosis47/tmodloader")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_.-]+", image):
            raise ValueError("Invalid repository/image")
        snapshot = collect(repository, image)
    write_snapshot(Path.cwd(), snapshot)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
