import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_support as support
import admin_settings as settings


class SupportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.console = self.root / 'Logs/container-console.log'; self.console.parent.mkdir()
        helper = patch.object(support.admin_updates, 'BASE', self.root); helper.start(); self.addCleanup(helper.stop)
        (self.root / 'VERSION').write_text('3.7.5')
        helper = patch.object(support.admin_updates, 'runtime', return_value={'tmodloader_version': 'v2026.08.3.0'}); helper.start(); self.addCleanup(helper.stop)
        self.private_helper = patch.object(support, 'known_private_values', return_value=['test-admin-credential', 'private-world', 'server-password-value'])
        self.private_helper.start(); self.addCleanup(self.private_helper.stop)

    def test_report_contains_useful_metadata_and_sanitizes_before_return(self):
        self.console.write_text('\n'.join([
            '[ERROR] Recipe loading failed in ExampleMod',
            '[ERROR] Token: test-admin-credential',
            '[ERROR] private-world failed with server-password-value',
            '[ERROR] Could not connect to 192.168.1.5:7777 or 2001:db8::1',
            '[ERROR] http://user:password@private.example/query?key=secret',
            '[ERROR] /home/alice/private/file and C:\\Users\\Alice\\file failed',
            '[ERROR] person@example.com failed',
            '[ERROR] player Alice joined from somewhere',
            '[ERROR] ``` injected markdown',
            '[INFO] This normal line must not be included',
        ]))
        result = support.report(self.console, {'available': True, 'mods': [{'name': 'Example Mod', 'internal_name': 'ExampleMod', 'version': '1.2.3'}]})['report']
        for expected in ['3.7.5', 'v2026.08.3.0', 'Example Mod', 'Recipe loading failed', '[IP]', '[PATH]', '[EMAIL]']:
            self.assertIn(expected, result)
        for secret in ['test-admin-credential', 'private-world', 'server-password-value', '192.168', '2001:db8', 'private.example', 'alice', 'Alice', 'person@example', 'normal line']:
            self.assertNotIn(secret, result)
        self.assertNotIn('``` injected', result)

    def test_bounded_tails_error_count_and_unavailable_logs(self):
        self.console.write_text('Error too old\n' + 'normal line\n' * 20000 + '\n'.join('ERROR issue ' + str(i) for i in range(60)))
        result = support.report(self.console, {'available': False})['report']
        self.assertNotIn('too old', result)
        self.assertNotIn('ERROR issue 0\n', result)
        self.assertIn('ERROR issue 59', result)
        self.assertIn('Loaded mods unavailable', result)
        self.console.unlink()
        self.assertIn('Recent logs unavailable', support.report(self.console, {})['report'])

    def test_sanitize_full_line_before_truncating(self):
        secret = 'a-private-value-that-crosses-the-display-boundary'
        result = support.sanitize('ERROR ' + ' ' * 980 + secret, [secret])
        self.assertNotIn('a-private-value', result)
        self.assertIn('[REDACTED]', result)
        self.assertEqual(support.sanitize('ERROR API_KEY = abc'), '[REDACTED: private log details]')

    def test_known_values_include_auth_env_and_persisted_password(self):
        # Stop only this test's mock to exercise actual collection.
        self.private_helper.stop()
        with patch.dict(os.environ, {'TMOD_GITHUB_TOKEN': 'github-fixture-secret', 'TMOD_PASS': 'env-password'}), \
                patch.object(settings, 'password_value', return_value='saved-password'), \
                patch.object(settings, 'read_json', return_value={'TMOD_WORLDNAME': 'My private world', 'TMOD_MODS': '123'}):
            values = support.known_private_values('request-admin-token')
        for value in ['request-admin-token', 'github-fixture-secret', 'env-password', 'saved-password', 'My private world']:
            self.assertIn(value, values)
        self.assertNotIn('123', values)

    def test_versions_and_mod_metadata_cannot_inject_report_sections(self):
        self.assertEqual(support.version('version\nPassword secret'), 'Unavailable')
        result = support.report(self.console, {'available': True, 'mods': [{'name': '<script>\nERROR test-admin-credential', 'version': 'secret-value', 'internal_name': 'x'}]})['report']
        self.assertNotIn('test-admin-credential', result)
        self.assertNotIn('secret-value', result)

    def test_failed_startup_reports_enabled_names_without_claiming_loaded(self):
        enabled = self.root / 'tModLoader/Mods/enabled.json'; enabled.parent.mkdir(parents=True)
        enabled.write_text(json.dumps(['ExampleMod', 'AnotherMod', 'test-admin-credential', 'bad\nname']))
        with patch.object(settings, 'DATA', self.root):
            result = support.report(self.console, {'available': False})['report']
        self.assertIn('Enabled mod filenames (loading not confirmed)', result)
        self.assertIn('ExampleMod', result)
        self.assertNotIn('test-admin-credential', result)
        self.assertNotIn('bad\nname', result)


if __name__ == '__main__':
    unittest.main()
