import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import admin_playthroughs as profiles
import admin_settings as settings

class PlaythroughTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        helper = patch.object(settings, 'PENDING', Path(temp.name)/'pending.json'); helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(settings, 'DATA', Path(temp.name)); helper.start(); self.addCleanup(helper.stop)
        world_dir = Path(temp.name)/'tModLoader/Worlds'; world_dir.mkdir(parents=True); (world_dir/'Keep.wld').write_bytes(b'world')
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web', 'TMOD_USECONFIGFILE': 'No'}); helper.start(); self.addCleanup(helper.stop)
        self.current = {'revision': 'r', 'staged': {'TMOD_MODS': '123,collection:456', 'TMOD_WORLDNAME': 'Keep'}, 'running': {'TMOD_MODS': '', 'TMOD_WORLDNAME': 'Keep'}}
    def change(self, **values):
        profiles.change({'revision': 'r', 'catalog_revision': profiles.catalog()['catalog_revision'], **values}, self.current)
    def save(self):
        self.change(action='save', name='Adventure', source='staged')
        return profiles.catalog()['playthroughs'][0]['id']
    def test_save_load_preserves_world_and_normalizes(self):
        key = self.save()
        self.current['staged']['TMOD_MODS'] = ''
        self.change(action='stage', id=key)
        self.assertEqual(settings.read_json(settings.PENDING), {'TMOD_MODS': '123,collection:456', 'TMOD_WORLDNAME': 'Keep'})
    def test_empty_running_profile_and_replace_confirmation(self):
        key = self.save()
        with self.assertRaises(ValueError): self.change(action='save', id=key, name='Adventure', source='running')
        self.change(action='save', id=key, name='Adventure', source='running', confirm=True)
        self.assertEqual(profiles.catalog()['playthroughs'][0]['settings']['TMOD_MODS'], '')
    def test_names_and_duplicates(self):
        self.save()
        for name in ['adventure', ' ', 'a\n', 'a'*65]:
            with self.assertRaises(ValueError): self.change(action='save', name=name, source='running')
    def test_stale_catalog_and_settings(self):
        old = profiles.catalog()['catalog_revision']; key = self.save()
        with self.assertRaises(ValueError): profiles.change({'action':'delete','id':key,'catalog_revision':old,'confirm':True}, self.current)
        with self.assertRaises(ValueError): self.change(action='stage', id=key, revision='old')
        self.assertFalse(settings.PENDING.exists())
    def test_rename_delete_and_env_guard(self):
        key = self.save(); self.change(action='rename', id=key, name='New')
        self.assertEqual(profiles.catalog()['playthroughs'][0]['name'], 'New')
        with patch.dict(os.environ, {'TMOD_CONFIG_SOURCE':'env'}):
            with self.assertRaises(ValueError): self.change(action='stage', id=key)
        with self.assertRaises(ValueError): self.change(action='delete', id=key)
        self.change(action='delete', id=key, confirm=True)
        self.assertEqual(profiles.catalog()['playthroughs'], [])
    def test_client_only_removals_are_reported(self):
        key = self.save()
        def clean(values, removed):
            removed.append('Client mod'); return {**values, 'TMOD_MODS':''}
        with patch.object(settings, 'clean_mod_selection', side_effect=clean): self.change(action='stage', id=key)
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_MODS'], '')
        self.assertEqual(settings.read_json(settings.PENDING.with_name('pending-removed.json'))['names'], ['Client mod'])
    def test_limit_does_not_overwrite_catalog(self):
        for i in range(50): self.change(action='save', name=str(i), source='running')
        with self.assertRaises(ValueError): self.change(action='save', name='Overflow', source='running')
        self.assertEqual(len(profiles.catalog()['playthroughs']), 50)

    def test_journey_settings_mods_and_world_loaded_together(self):
        self.current['staged'].update(TMOD_JOURNEY_GODMODE='2', TMOD_MAXPLAYERS='5', TMOD_DIFFICULTY='3')
        key = self.save()
        self.current['staged'].update(TMOD_JOURNEY_GODMODE='0', TMOD_MAXPLAYERS='10', TMOD_MODS='999')
        self.change(action='stage', id=key)
        draft = settings.read_json(settings.PENDING)
        self.assertEqual(draft['TMOD_JOURNEY_GODMODE'], '2')
        self.assertEqual(draft['TMOD_MAXPLAYERS'], '10')
        self.assertEqual(draft['TMOD_MODS'], '123,collection:456')
        self.assertNotIn('TMOD_MAXPLAYERS', profiles.catalog()['playthroughs'][0]['settings'])
        profiles.worlds.validate_pending()

    def test_missing_world_rejected_at_load_and_apply(self):
        key = self.save()
        self.change(action='stage', id=key)
        (profiles.worlds.directory()/'Keep.wld').unlink()
        with self.assertRaises(ValueError): profiles.worlds.validate_pending()
        with self.assertRaises(ValueError): self.change(action='stage', id=key)

    def test_custom_config_cannot_load(self):
        key = self.save()
        with patch.dict(os.environ, {'TMOD_USECONFIGFILE':'Yes'}):
            with self.assertRaises(ValueError): self.change(action='stage', id=key)
