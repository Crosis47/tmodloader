import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_modconfigs as configs
import admin_profile_configs as snapshots
import admin_profiles as profiles
import admin_settings as settings


class ProfileConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for key, value in [('DATA', self.root), ('PENDING', self.root / 'admin/pending.json')]:
            helper = patch.object(settings, key, value); helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web'}); helper.start(); self.addCleanup(helper.stop)
        self.path = self.root / 'tModLoader/ModConfigs/Example.json'
        self.path.parent.mkdir(parents=True)
        self.original = b'\xef\xbb\xbf{\r\n  "enabled": true\r\n}\r\n'
        self.path.write_bytes(self.original)
        self.current = {'revision': 'r', 'running': {'TMOD_MODS': ''}, 'staged': {'TMOD_MODS': '', 'TMOD_WORLDNAME': 'Keep'}}

    def change(self, **values):
        profiles.change({'revision': 'r', 'catalog_revision': profiles.catalog()['catalog_revision'], **values}, self.current)

    def save(self):
        self.change(action='save', name='Pack', source='running', configs=['ModConfigs/Example.json'])
        return profiles.catalog()['profiles'][0]['id']

    def test_snapshot_is_private_and_stage_does_not_write_until_apply(self):
        key = self.save()
        public = json.dumps(profiles.public_catalog())
        self.assertNotIn('enabled', public)
        self.assertNotIn(base64.b64encode(self.original).decode(), public)
        changed = b'{"enabled":false}'
        self.path.write_bytes(changed)
        self.change(action='stage', id=key)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_WORLDNAME'], 'Keep')
        with snapshots.applying():
            self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(configs.previous('ModConfigs/Example.json')['data'], changed)
        with snapshots.applying():  # Safe retry after game startup failed.
            self.assertEqual(self.path.read_bytes(), self.original)

    def test_mods_only_load_clears_prior_staged_configs(self):
        key = self.save(); self.path.write_text('{"enabled":false}')
        self.change(action='stage', id=key)
        self.assertEqual(len(snapshots.pending()), 1)
        self.change(action='stage', id=key, include_configs=False)
        self.assertEqual(snapshots.pending(), [])
        self.assertEqual(json.loads(self.path.read_text()), {'enabled': False})

    def test_changed_disk_fails_before_any_write(self):
        key = self.save(); self.path.write_text('{"enabled":false}')
        self.change(action='stage', id=key)
        self.path.write_text('{"newer":true}')
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            snapshots.check_pending()
        with self.assertRaises(ValueError):
            with snapshots.applying():
                self.fail('Stale batch must not be applied')
        self.assertEqual(self.path.read_text(), '{"newer":true}')

    def test_matching_snapshot_is_still_checked_for_later_disk_edits(self):
        key = self.save()
        self.change(action='stage', id=key)
        self.assertEqual(len(snapshots.pending()), 1)
        self.path.write_text('{"later":true}')
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            snapshots.check_pending()

    def test_rollback_preserves_newer_external_changes(self):
        key = self.save(); self.path.write_text('{"disk":true}')
        self.change(action='stage', id=key)
        with self.assertRaisesRegex(ValueError, 'Newer edits were preserved'):
            with snapshots.applying():
                self.path.write_text('{"external":true}')
                raise OSError('Later operation failed')
        self.assertEqual(self.path.read_text(), '{"external":true}')

    def test_multi_file_write_failure_restores_files_and_history(self):
        other = self.path.with_name('Other.json'); other.write_text('{}')
        records = snapshots.capture(['ModConfigs/Example.json', 'ModConfigs/Other.json'])
        self.path.write_text('{"old":true}'); other.write_text('{"other":true}')
        settings.atomic_json(snapshots.pending_path(), snapshots.stage(records))
        old = self.path.read_bytes()
        write = configs.write_version
        def fail_second(current, data):
            if current['name'].endswith('Other.json'):
                raise OSError('Disk full')
            return write(current, data)
        with patch.object(configs, 'write_version', side_effect=fail_second):
            with self.assertRaises(OSError):
                with snapshots.applying():
                    pass
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(other.read_text(), '{"other":true}')
        self.assertFalse(configs.history_path('ModConfigs/Example.json').exists())

    def test_later_settings_failure_restores_configs_and_previous_history(self):
        key = self.save()
        configs.save({**configs.read('ModConfigs/Example.json'), 'content': '{"changed":true}'})
        old_history = configs.history_path('ModConfigs/Example.json').read_bytes()
        self.change(action='stage', id=key)
        with self.assertRaises(OSError):
            with snapshots.applying():
                raise OSError('Settings could not be promoted')
        self.assertEqual(self.path.read_text(), '{"changed":true}')
        self.assertEqual(configs.history_path('ModConfigs/Example.json').read_bytes(), old_history)

    def test_invalid_missing_duplicate_and_unsafe_paths_do_not_save(self):
        for names in [['../secret.json'], ['config.json'], ['ModConfigs/Example.json'] * 2, ['ModConfigs/missing.json'], 'wrong', ['x'] * 65]:
            with self.assertRaises(ValueError):
                self.change(action='save', name='Bad', source='running', configs=names)
        self.path.write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'Invalid JSON'):
            self.save()
        self.assertEqual(profiles.catalog()['profiles'], [])

    def test_changed_snapshot_checksum_fails_closed(self):
        records = snapshots.capture(['ModConfigs/Example.json'])
        records[0]['revision'] = '0' * 64
        with self.assertRaises(ValueError):
            snapshots.stage(records)

    def test_large_snapshot_and_storage_bounds(self):
        self.path.write_text(json.dumps({'large': 'x' * 70000}))
        self.save()
        self.assertEqual(len(profiles.catalog()['profiles']), 1)
        with patch.object(snapshots, 'SNAPSHOT_LIMIT', 100):
            with self.assertRaises(ValueError):
                snapshots.capture(['ModConfigs/Example.json'])
        with patch.object(snapshots, 'STORAGE_LIMIT', 100):
            with self.assertRaises(ValueError):
                profiles.catalog()

    def test_failed_stage_preserves_previous_draft_configs(self):
        settings.atomic_json(snapshots.pending_path(), [])
        original = snapshots.pending_path().read_bytes()
        atomic = settings.atomic_json
        def fail_pending(path, value):
            if path == settings.PENDING:
                raise OSError('Disk full')
            return atomic(path, value)
        with patch.object(settings, 'atomic_json', side_effect=fail_pending):
            with self.assertRaises(OSError):
                snapshots.stage_draft([{'test': 1}], {})
        self.assertEqual(snapshots.pending_path().read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
