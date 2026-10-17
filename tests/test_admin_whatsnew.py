import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_settings as settings
import admin_whatsnew as news


class WhatsNewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for owner, key, value in [(settings, 'PENDING', self.root / 'admin/pending.json'), (news, 'BASE', self.root)]:
            helper = patch.object(owner, key, value); helper.start(); self.addCleanup(helper.stop)
        self.release('3.8.0')

    def release(self, value):
        (self.root / 'VERSION').write_text(value)
        (self.root / 'release-highlights.json').write_text(json.dumps({'version': value, 'highlights': [{'title': 'New feature', 'description': 'Useful changes.'}]}))

    def test_fresh_install_baseline_does_not_show(self):
        news.initialize(False)
        self.assertFalse(news.status()['pending'])
        news.initialize(True)  # Saved credentials now exist, same release.
        self.assertFalse(news.status()['pending'])

    def test_existing_install_gets_first_notice_and_persistent_dismissal(self):
        news.initialize(True)
        self.assertTrue(news.status()['pending'])
        news.initialize(True)
        self.assertTrue(news.status()['pending'])
        news.dismiss({'version': '3.8.0'})
        news.initialize(True)
        self.assertFalse(news.status()['pending'])
        self.assertEqual(news.status()['url'], 'https://github.com/Crosis47/tmodloader/releases/tag/3.8.0')

    def test_newer_upgrade_shows_again_but_downgrade_does_not(self):
        news.initialize(False)
        self.release('3.9.0'); news.initialize(True)
        self.assertTrue(news.status()['pending'])
        news.dismiss({'version': '3.9.0'})
        self.release('3.8.0'); news.initialize(True)
        self.assertFalse(news.status()['pending'])

    def test_stale_dismissal_cannot_hide_new_release(self):
        news.initialize(True)
        with self.assertRaises(ValueError): news.dismiss({'version': '3.7.5'})
        self.assertTrue(news.status()['pending'])

    def test_missing_mismatched_or_invalid_content_unavailable(self):
        path = self.root / 'release-highlights.json'
        for data in [{}, [], {'version': '3.7.5', 'highlights': []}, {'version': '3.8.0', 'highlights': [{'title': 'Missing description'}]}]:
            path.write_text(json.dumps(data))
            self.assertFalse(news.status()['available'])
        path.unlink()
        self.assertFalse(news.status()['available'])

    def test_packaged_highlights_match_version(self):
        root = Path(__file__).resolve().parents[1]
        with patch.object(news, 'BASE', root):
            self.assertEqual(news.highlights()['version'], (root / 'VERSION').read_text().strip())
