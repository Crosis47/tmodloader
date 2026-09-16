import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import admin_journey as journey
import admin_settings as settings
import admin_server as server
import admin_worlds as worlds
from test_admin_world_metadata import world_header


class JourneyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for key, value in [('DATA', self.root), ('ACTIVE', self.root / 'admin/settings.json'),
                           ('PENDING', self.root / 'admin/pending.json'), ('RUNTIME', self.root / 'runtime')]:
            helper = patch.object(settings, key, value)
            helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(server.admin_metrics, 'STATE', self.root / 'backup.json')
        helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web', 'TMOD_USECONFIGFILE': 'No',
                                        'TMOD_WORLDNAME': 'First', 'TMOD_JOURNEY_GODMODE': '1'})
        helper.start(); self.addCleanup(helper.stop)
        server.JOB = {'state': 'idle'}
        worlds.directory().mkdir(parents=True)
        for name in ['First', 'Second']:
            (worlds.directory() / (name + '.wld')).write_bytes(world_header(mode=3))
        (worlds.directory() / 'Classic.wld').write_bytes(world_header(mode=0))
        self.running = {'TMOD_WORLDNAME': 'First', **journey.defaults(), 'TMOD_MOTD': 'Keep me'}
        settings.atomic_json(settings.RUNTIME / 'admin-effective.json', self.running)
        settings.atomic_json(settings.ACTIVE, self.running)

    def save(self, name, override, value):
        state = server.api('GET', '/api/worlds/journey', {'name': [name]} if name else {}, {})
        return server.api('POST', '/api/worlds/journey', {}, {
            'name': name, 'override': override, 'revision': state['revision'],
            'settings_revision': state['settings_revision'],
            'permissions': {**state['permissions'], 'TMOD_JOURNEY_GODMODE': value}})

    def test_inheritance_override_reset_and_world_switch(self):
        self.save(None, False, '2')
        self.assertEqual(journey.effective('Second')['TMOD_JOURNEY_GODMODE'], '2')
        self.save('Second', True, '0')
        self.save(None, False, '1')
        self.assertEqual(journey.effective('Second')['TMOD_JOURNEY_GODMODE'], '0')
        self.assertEqual(journey.effective('First')['TMOD_JOURNEY_GODMODE'], '1')
        worlds.stage({'action': 'switch', 'name': 'Second'}, server.configuration())
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_JOURNEY_GODMODE'], '0')
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_MOTD'], 'Keep me')
        self.save('Second', False, '0')
        self.assertFalse(journey.state('Second')['override'])
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_JOURNEY_GODMODE'], '1')

    def test_inactive_save_does_not_change_running_or_draft(self):
        self.save('Second', True, '2')
        self.assertFalse(settings.PENDING.exists())
        self.assertEqual(settings.read_json(settings.ACTIVE), self.running)
        self.assertEqual(settings.read_json(settings.RUNTIME / 'admin-effective.json'), self.running)

    def test_defaults_do_not_queue_unused_permissions_for_classic_world(self):
        settings.atomic_json(settings.RUNTIME / 'admin-effective.json', {**self.running, 'TMOD_WORLDNAME': 'Classic'})
        self.save(None, False, '2')
        self.assertFalse(settings.PENDING.exists())
        self.assertEqual(journey.defaults()['TMOD_JOURNEY_GODMODE'], '2')

    def test_new_world_inherits_defaults(self):
        self.save(None, False, '2')
        worlds.stage({'action': 'create', 'name': 'NewJourney', 'creation': {
            'TMOD_WORLDSIZE': '1', 'TMOD_DIFFICULTY': '3',
            'TMOD_WORLDEVIL': 'random', 'TMOD_WORLDSEED': ''}}, server.configuration())
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_JOURNEY_GODMODE'], '2')

    def test_boot_uses_override_without_changing_defaults(self):
        self.save('First', True, '2')
        self.assertEqual(settings.boot_values()['TMOD_JOURNEY_GODMODE'], '2')
        self.assertEqual(journey.defaults()['TMOD_JOURNEY_GODMODE'], '1')

    def test_applied_playthrough_remembers_its_snapshot(self):
        journey.remember_applied({**self.running, 'TMOD_JOURNEY_GODMODE': '2'})
        self.assertTrue(journey.state('First')['override'])
        self.assertEqual(journey.effective('Second')['TMOD_JOURNEY_GODMODE'], '1')

    def test_stale_revision_and_unknown_fields(self):
        state = journey.state('Second')
        self.save(None, False, '2')
        with self.assertRaisesRegex(ValueError, 'changed'):
            journey.save({**state, 'override': True})
        state = journey.state('Second')
        with self.assertRaisesRegex(ValueError, 'no other settings'):
            journey.save({**state, 'override': True, 'permissions': {**state['permissions'], 'TMOD_PASS': 'no'}})

    def test_non_journey_world_and_operation_guards(self):
        with self.assertRaisesRegex(ValueError, 'confirmed Journey'):
            server.api('GET', '/api/worlds/journey', {'name': ['Classic']}, {})
        with patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'env'}):
            with self.assertRaisesRegex(ValueError, 'web-managed'):
                self.save('First', True, '2')
        server.JOB = {'state': 'running'}
        with self.assertRaisesRegex(ValueError, 'current operation'):
            self.save('First', True, '2')

    def test_unchanged_draft_is_not_pending_and_hidden_settings_have_diffs(self):
        settings.atomic_json(settings.PENDING, self.running)
        state = server.configuration()
        self.assertFalse(state['pending'])
        self.assertTrue(state['draft_exists'])
        self.assertEqual(state['changes'], [])
        settings.atomic_json(settings.PENDING, {**self.running, 'TMOD_WORLDNAME': 'Second'})
        state = server.configuration()
        self.assertTrue(state['pending'])
        self.assertEqual(state['changes'], [{'key': 'TMOD_WORLDNAME', 'label': 'World name',
                                             'running': 'First', 'staged': 'Second'}])
