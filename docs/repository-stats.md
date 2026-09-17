# README statistics

**Refresh README statistics** runs hourly at minute 23 UTC and can also be run
manually from Actions. GitHub may delay scheduled jobs. The README shows the
actual successful collection time; these are periodic snapshots, not live counters.

The workflow generates SVG badges in this repository, without Shields.io. Each
badge's filename includes a hash of its contents. When a value changes its image
URL changes too, avoiding reuse of an older cached badge on GitHub or Docker Hub.
Unchanged values reuse their existing image. The original CI/publisher status
badges still use Shields.io; the new numeric statistics do not.
Older small SVG assets are retained so cached and historical README links keep working.

| Badge | Source and meaning |
| --- | --- |
| Docker pulls / stars | Docker Hub's public repository API counters. |
| GHCR pulls | Total downloads displayed on the public GitHub container-package page. |
| GHCR downloads / 7d | Sum of the latest seven dated bars in that page's download chart, including its current partial day. Exact window dates are stored in `docs/stats/latest.json`. |
| GitHub stars / forks | GitHub repository API counters. |
| Issues open / closed | GitHub issue searches explicitly excluding pull requests. |
| PRs open / merged | GitHub pull-request searches; merged excludes closed, unmerged PRs. |

Container downloads are registry-reported counts, not unique users, installations,
or source-code clones. GitHub release-asset downloads are a different metric:
this project currently distributes container images and has no uploaded release
assets, so the weekly download badge refers to GHCR. Docker Hub does not expose
an equivalent public seven-day series in its repository API.

The GHCR collector reads the same public package page used by `ghcr-stats`, but
selects chart bars by date rather than position and validates the data. This
avoids adding another action dependency and rejects stale/incomplete charts.
An upstream error or changed page markup fails the job and preserves the previous
snapshot and its timestamp; errors are never converted into zero downloads.

Only the marked README block and generated `docs/stats` files are committed.
Rebasing preserves unrelated changes and stops on conflicts instead of overwriting
them. No new secrets are required: collection uses public registry data and the
built-in GitHub token. The workflow then explicitly invokes the Docker Hub Overview
sync with the generated commit, because bot commits do not trigger another push
workflow. The existing Docker Hub secret remains scoped to that Overview job.

To validate locally:

```bash
python3 -m unittest discover -s tests -p 'test_readme_stats.py' -v
GITHUB_REPOSITORY=Crosis47/tmodloader DOCKERHUB_IMAGE=crosis47/tmodloader \
  python3 .github/scripts/readme-stats.py
```

The collector needs authenticated `gh`, `curl`, and Python. The generated JSON
and badges are public and contain no credentials or private traffic analytics.
