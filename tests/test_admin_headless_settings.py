"""Headless startup must not restore saved WebUI configuration."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_settings as settings


class HeadlessSettingsTests(unittest.TestCase):
    def test_headless_ignores_saved_settings_and_password(self):
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / 'settings.json'
            active.write_text('{"TMOD_WORLDNAME": "SavedWorld"}', encoding='utf-8')
            before = active.read_bytes()
            with patch.dict(os.environ, {'TMOD_WEB_ENABLED': '0',
                    'TMOD_CONFIG_SOURCE': 'web', 'TMOD_WORLDNAME': 'EnvWorld',
                    'TMOD_PASS': 'environment-password', 'TMOD_USECONFIGFILE': 'Yes'}), \
                    patch.object(settings, 'ACTIVE', active), \
                    patch.object(settings, 'password_value') as password:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    settings.main('boot')
                    settings.main('password')
                self.assertEqual(output.getvalue().strip(), '')
                self.assertEqual(settings.effective()['TMOD_WORLDNAME'], 'EnvWorld')
                password.assert_not_called()
                self.assertEqual(active.read_bytes(), before)
                self.assertFalse(settings.web_mode())
                with patch.dict(os.environ, {'TMOD_WEB_ENABLED': '1'}):
                    self.assertTrue(settings.web_mode())

    def test_enabled_environment_mode_remains_authoritative(self):
        with patch.dict(os.environ, {'TMOD_WEB_ENABLED': '1', 'TMOD_CONFIG_SOURCE': 'env'}):
            self.assertFalse(settings.web_mode())

    def test_default_mode_follows_webui(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(settings.web_mode())
            with patch.dict(os.environ, {'TMOD_WEB_ENABLED': '0'}):
                self.assertFalse(settings.web_mode())
            with patch.dict(os.environ, {'TMOD_WEB_ENABLED': '1'}):
                self.assertTrue(settings.web_mode())
