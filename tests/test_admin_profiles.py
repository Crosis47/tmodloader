import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import admin_profiles as profiles
import admin_settings as settings

class ProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        helper = patch.object(settings, 'PENDING', Path(temp.name)/'pending.json'); helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web'}); helper.start(); self.addCleanup(helper.stop)
        self.current = {'revision': 'r', 'staged': {'TMOD_MODS': '123,collection:456', 'TMOD_WORLDNAME': 'Keep'}, 'running': {'TMOD_MODS': ''}}
    def change(self, **values):
        profiles.change({'revision': 'r', 'catalog_revision': profiles.catalog()['catalog_revision'], **values}, self.current)
    def save(self):
        self.change(action='save', name='Adventure', source='staged')
        return profiles.catalog()['profiles'][0]['id']
    def test_save_load_preserves_world_and_normalizes(self):
        key = self.save()
        self.current['staged']['TMOD_MODS'] = ''
        self.change(action='stage', id=key)
        self.assertEqual(settings.read_json(settings.PENDING), {'TMOD_MODS': '123,collection:456', 'TMOD_WORLDNAME': 'Keep'})
    def test_empty_running_profile_and_replace_confirmation(self):
        key = self.save()
        with self.assertRaises(ValueError): self.change(action='save', id=key, name='Adventure', source='running')
        self.change(action='save', id=key, name='Adventure', source='running', confirm=True)
        self.assertEqual(profiles.catalog()['profiles'][0]['mods'], '')
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
        self.assertEqual(profiles.catalog()['profiles'][0]['name'], 'New')
        with patch.dict(os.environ, {'TMOD_CONFIG_SOURCE':'env'}):
            with self.assertRaises(ValueError): self.change(action='stage', id=key)
        with self.assertRaises(ValueError): self.change(action='delete', id=key)
        self.change(action='delete', id=key, confirm=True)
        self.assertEqual(profiles.catalog()['profiles'], [])
    def test_client_only_removals_are_reported(self):
        key = self.save()
        def clean(values, removed):
            removed.append('Client mod'); return {'TMOD_MODS':''}
        with patch.object(settings, 'clean_mod_selection', side_effect=clean): self.change(action='stage', id=key)
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_MODS'], '')
        self.assertEqual(settings.read_json(settings.PENDING.with_name('pending-removed.json'))['names'], ['Client mod'])
    def test_limit_does_not_overwrite_catalog(self):
        for i in range(50): self.change(action='save', name=str(i), source='running')
        with self.assertRaises(ValueError): self.change(action='save', name='Overflow', source='running')
        self.assertEqual(len(profiles.catalog()['profiles']), 50)
