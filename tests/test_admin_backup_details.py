import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_backup_details as details
import backup


class BackupDetailsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'data'
        self.dest = self.root / 'backups'
        self.dest.mkdir()
        for name, content in {
            'tModLoader/Worlds/Example.wld': 'world data',
            'tModLoader/Mods/enabled.json': '["ExampleMod"]',
            'tModLoader/Logs/server.log': 'Starting tModLoader server 1.4.4.9+2026.7.3.0|2026.7|stable|',
            'admin/settings.json': '{"TMOD_WORLDNAME":"DraftWorld","TMOD_MODS":"123"}',
        }.items():
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.runtime = {'tmodloader_version': 'v2026.07.3.0', 'tmodloader_sha256': 'binary'}
        self.info = {'Image': 'old-build', 'Config': {'Image': 'old-image'},
                     'Runtime': self.runtime, 'Running': {'TMOD_WORLDNAME': 'Example', 'TMOD_MODS': '456'}}
        self.bundle = backup.create_backup(self.data, self.dest, self.info)
        self.addCleanup(patch.stopall)
        patch.object(details, 'current_runtime', return_value=self.runtime).start()
        patch.object(details, 'current_build', return_value='new-build').start()

    def test_inspection_uses_running_world_and_actual_contents(self):
        result = details.inspect_archive(self.bundle)
        self.assertEqual(result['snapshot']['active_world'], 'Example')
        self.assertEqual(result['snapshot']['worlds'], ['Example.wld'])
        self.assertEqual(result['snapshot']['enabled_mods'], ['ExampleMod'])
        self.assertEqual(result['snapshot']['workshop'], ['456'])
        self.assertTrue(result['compatibility']['can_prepare'])

    def test_preparation_preserves_original_and_payload(self):
        original = {path.name: path.read_bytes() for path in self.bundle.iterdir()}
        result = details.prepare(self.bundle, self.dest, backup.digest(self.bundle / 'data.tar.gz'))
        prepared = self.dest / result['archive']
        metadata = backup.validate(prepared)
        self.assertEqual(metadata['image_id'], 'new-build')
        self.assertEqual(metadata['prepared_from']['archive'], self.bundle.name)
        self.assertEqual((prepared / 'data.tar.gz').read_bytes(), original['data.tar.gz'])
        self.assertEqual({path.name: path.read_bytes() for path in self.bundle.iterdir()}, original)
        backup.retain(self.dest, 1, prepared)
        self.assertTrue(self.bundle.exists(), 'Old-build originals must survive current-build retention')

    def test_old_manifest_can_use_recorded_game_log_version(self):
        manifest = self.bundle / 'manifest.json'
        metadata = json.loads(manifest.read_text())
        metadata.pop('snapshot'); metadata.pop('runtime')
        manifest.write_text(json.dumps(metadata))
        result = details.inspect_archive(self.bundle)
        self.assertTrue(result['compatibility']['can_prepare'])
        self.assertEqual(result['snapshot']['active_world_source'], 'Saved dashboard settings')

    def test_different_unknown_or_modified_game_rejected(self):
        metadata = backup.validate(self.bundle)
        for runtime in ({}, {'tmodloader_version': '2026.8.1.0'},
                        {**self.runtime, 'tmodloader_sha256': 'different'}):
            with self.subTest(runtime=runtime):
                self.assertFalse(details.compatibility(metadata, runtime, 'new-build')['can_prepare'])
        self.assertFalse(details.compatibility(metadata, self.runtime, '')['can_prepare'])
        self.assertTrue(details.compatibility(metadata, self.runtime, 'old-build')['matches_current'])

    def test_stale_checksum_and_low_space_leave_no_copy(self):
        with self.assertRaisesRegex(ValueError, 'changed since inspection'):
            details.prepare(self.bundle, self.dest, '0' * 64)
        with patch.object(details.shutil, 'disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaisesRegex(ValueError, 'Insufficient'):
                details.prepare(self.bundle, self.dest, backup.digest(self.bundle / 'data.tar.gz'))
        self.assertEqual(list(self.dest.iterdir()), [self.bundle])

    def test_corrupt_archive_is_not_prepared(self):
        with (self.bundle / 'data.tar.gz').open('ab') as stream:
            stream.write(b'corruption')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            details.inspect_archive(self.bundle)


if __name__ == '__main__':
    unittest.main()
