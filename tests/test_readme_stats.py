from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location(
    "stats", Path(__file__).resolve().parents[1] / ".github/scripts/readme-stats.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def chart(days=30, reverse=False):
    end = date(2026, 9, 17)
    values = [(end - timedelta(days=i), i + 1) for i in range(days)]
    if reverse:
        values.reverse()
    return ('<div><span>Total downloads</span><h3 title="1,581">1.58K</h3></div>'
            '<div aria-label="Downloads for the last 30 days"><svg>' +
            ''.join(f'<rect data-date="{day}" data-merge-count="{value}"></rect>'
                    for day, value in values) + '</svg></div>')


class StatsTests(unittest.TestCase):
    def test_week_uses_dates_in_either_dom_order(self):
        for reverse in (True, False):
            result = stats.package_counts(chart(reverse=reverse), date(2026, 9, 17))
            self.assertEqual(result["ghcr_pulls"], 1581)
            self.assertEqual(result["ghcr_week"], 28)
            self.assertEqual(result["ghcr_week_start"], "2026-09-11")

    def test_missing_chart_does_not_become_zero(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            stats.package_counts('<html>Sign in</html>', date(2026, 9, 17))

    def test_incomplete_or_stale_chart_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing dates"):
            stats.package_counts(chart(days=6), date(2026, 9, 17))
        with self.assertRaisesRegex(ValueError, "stale"):
            stats.package_counts(chart(), date(2026, 9, 20))

    def test_duplicate_dates_rejected(self):
        broken = chart().replace('2026-09-16', '2026-09-17')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            stats.package_counts(broken, date(2026, 9, 17))

    def test_badge_escapes_xml_and_accepts_zero(self):
        root = ET.fromstring(stats.badge('Issues & PRs', 0, '087CA7'))
        self.assertEqual(root.attrib['aria-label'], 'ISSUES & PRS: 0')
        for invalid in (None, -1, True, '0', 1.5):
            with self.assertRaises(ValueError):
                stats.badge('Count', invalid, '087CA7')

    def snapshot(self):
        return {'repository': 'owner/repo', 'docker_image': 'owner/image',
                'updated_at': '2026-09-17 12:00 UTC', 'metrics': dict.fromkeys([
                    'docker_pulls', 'docker_stars', 'ghcr_pulls', 'ghcr_day', 'ghcr_week',
                    'github_stars', 'github_forks', 'issues_open', 'issues_closed',
                    'prs_open', 'prs_merged'], 0)}

    def test_content_addressed_images_and_readme_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = f'Before\n{stats.START}\nold\n{stats.END}\nAfter\n'
            (root / 'README.md').write_text(text)
            snapshot = self.snapshot()
            stats.write_snapshot(root, snapshot)
            first = set((root / 'docs/stats/badges').glob('*.svg'))
            self.assertEqual(len(first), 10)
            snapshot['metrics']['docker_pulls'] = 300
            stats.write_snapshot(root, snapshot)
            second = set((root / 'docs/stats/badges').glob('*.svg'))
            self.assertEqual(len(first & second), 10)
            self.assertEqual(len(second), 11)
            readme = (root / 'README.md').read_text()
            self.assertTrue(readme.startswith('Before\n'))
            self.assertTrue(readme.endswith('\nAfter\n'))
            self.assertNotIn('shields.io', readme)
            for path in second:
                ET.fromstring(path.read_text())
                if path not in first or not path.name.startswith('docker_pulls-'):
                    self.assertIn(path.name, readme)

    def test_bad_data_or_missing_markers_leaves_readme_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = f'Before\n{stats.START}\n{stats.END}\nAfter'
            path = root / 'README.md'
            path.write_text(original)
            snapshot = self.snapshot()
            snapshot['metrics']['prs_merged'] = None
            with self.assertRaises(ValueError):
                stats.write_snapshot(root, snapshot)
            self.assertEqual(path.read_text(), original)
            self.assertFalse((root / 'docs/stats').exists())
            path.write_text('No markers')
            with self.assertRaisesRegex(ValueError, 'marker'):
                stats.write_snapshot(root, self.snapshot())

    def test_issue_searches_exclude_prs_and_fail_on_incomplete_results(self):
        responses = [{'stargazers_count': 0, 'forks_count': 0},
                     {'total_count': 0, 'incomplete_results': True}]
        with patch.object(stats, 'public_text', return_value=json.dumps({'pull_count': 1, 'star_count': 0})), \
                patch.object(stats, 'github_json', side_effect=responses) as request:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                stats.collect('owner/repo', 'owner/image')
            self.assertIn('q=repo:owner/repo is:issue is:open', request.call_args.args)


if __name__ == '__main__':
    unittest.main()
