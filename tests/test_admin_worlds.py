import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_worlds as worlds
import admin_settings as settings


class WorldTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key, value in [('DATA', self.root), ('PENDING', self.root / 'admin/pending.json')]:
            helper = patch.object(settings, key, value)
            helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web', 'TMOD_USECONFIGFILE': 'No'})
        helper.start(); self.addCleanup(helper.stop)
        worlds.directory().mkdir(parents=True)
        self.current = {'staged': {'TMOD_WORLDNAME': 'Old', 'TMOD_MAXPLAYERS': '5'}}
        self.creation = {'TMOD_WORLDSIZE': '1', 'TMOD_DIFFICULTY': '1', 'TMOD_WORLDEVIL': 'crimson', 'TMOD_WORLDSEED': ''}

    def test_inventory_saved_files_selected_and_sidecar(self):
        (worlds.directory() / 'Old.wld').write_bytes(b'world')
        (worlds.directory() / 'Old.twld').write_bytes(b'mod')
        (worlds.directory() / 'Old.wld.bak').write_bytes(b'backup')
        result = worlds.inventory({'TMOD_WORLDNAME': 'Old'})
        self.assertEqual(len(result['worlds']), 1)
        self.assertTrue(result['worlds'][0]['selected'])
        self.assertTrue(result['worlds'][0]['has_mod_data'])
        self.assertEqual(result['worlds'][0]['bytes'], 5)

    def test_create_preserves_other_staged_settings(self):
        worlds.stage({'action': 'create', 'name': 'New', 'creation': self.creation}, self.current)
        values = settings.read_json(settings.PENDING)
        self.assertEqual(values['TMOD_MAXPLAYERS'], '5')
        self.assertEqual(values['TMOD_WORLDNAME'], 'New')
        self.assertEqual(values['TMOD_WORLDEVIL'], 'crimson')
        worlds.validate_pending()

    def test_create_rejects_existing_world_sidecar_and_backup(self):
        for suffix in ('.wld', '.twld', '.wld.bak', '.twld.bak'):
            path = worlds.directory() / ('New' + suffix)
            path.write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError, 'already has saved files'):
                worlds.check('create', 'New')
            path.unlink()

    def test_switch_rechecks_disappeared_world(self):
        path = worlds.directory() / 'Other.wld'
        path.write_bytes(b'world')
        worlds.stage({'action': 'switch', 'name': 'Other'}, self.current)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or empty'):
            worlds.validate_pending()

    def test_creation_rechecks_newly_occupied_name(self):
        worlds.stage({'action': 'create', 'name': 'New', 'creation': self.creation}, self.current)
        (worlds.directory() / 'New.wld').write_bytes(b'new file')
        with self.assertRaisesRegex(ValueError, 'already has saved files'):
            worlds.validate_pending()

    def test_paths_and_links_rejected(self):
        for name in ('../escape', '/absolute', 'a\\b', '', '..', 'x\nexit'):
            with self.assertRaises(ValueError):
                worlds.check('create', name)
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError):
                worlds.check('create', 'Safe')

    def test_creation_length_and_unknown_settings_rejected(self):
        for name, creation in [('x' * 27, self.creation), ('Okay', {**self.creation, 'TMOD_WORLDSEED': 'x' * 40}), ('Okay', {**self.creation, 'TMOD_PASS': 'secret'})]:
            with self.assertRaises(ValueError):
                worlds.stage({'action': 'create', 'name': name, 'creation': creation}, self.current)

    def test_custom_configuration_does_not_claim_active_world(self):
        with patch.dict(os.environ, {'TMOD_USECONFIGFILE': 'Yes'}):
            result = worlds.inventory({'TMOD_WORLDNAME': 'Old'})
            self.assertFalse(result['editable'])
            self.assertIsNone(result['configured'])
