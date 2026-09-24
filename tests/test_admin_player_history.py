import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import admin_player_history as history
import admin_settings as settings
import console_tee
import admin_players
from test_admin_world_metadata import world_header


class HistoryTests(unittest.TestCase):
    def test_same_name_sessions_share_history_with_separate_ban_targets(self):
        tracker = self.tracker()
        tracker.event_key = 'test-only'
        tracker.feed(b'[CHARACTER] {"key":"test-only","data":{"action":"ready"}}\n')
        def event(session, address):
            tracker.feed((': [CHARACTER] ' + json.dumps({'key': 'test-only', 'data': {
                'action': 'joined', 'session': session * 32, 'name': 'Alex', 'address': address}}) + '\n').encode())
        event('a', '203.0.113.1:2345')
        event('a', '203.0.113.1:2345')
        event('b', '203.0.113.2:2345')
        tracker.feed(b'Alex has joined.\n')
        state = history.history()['world']
        self.assertEqual(state['total'], 1)
        player = state['players'][0]
        self.assertEqual(player['visits'], 2)
        self.assertNotIn('appearance', player)
        self.assertEqual({i['identifier'] for i in player['identities']}, {'203.0.113.1', '203.0.113.2'})
        for identity in player['identities']:
            self.assertEqual(history.ban_target(identity['key'])['name'], 'Alex')

    def test_legacy_appearance_records_preserve_visits_and_ban_evidence(self):
        tracker = self.tracker()
        history.record('Alex', tracker.world)
        history.observe('Alex', '203.0.113.7:1234', tracker.world, 'Native player query')
        with history.connection(write=True) as db:
            for number in (1, 2):
                key = '@character:' + str(number) * 64
                db.execute('INSERT INTO characters VALUES (?, ?, ?)', (key, 'Alex', '{}'))
                for world in ('', tracker.world):
                    db.execute('INSERT INTO visits VALUES (?, ?, ?, ?, ?)', (world, key, '2026-01-01', '2026-02-01', 3))
                    db.execute('INSERT INTO identities VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                               (world, key, '203.0.113.8', str(number) * 64, 'ip', 'Server character tracking', '2026-01-01', '2026-02-01'))
        for scope in ('world', 'server'):
            state = history.history()['' + scope]
            self.assertEqual(state['total'], 1)
            player = state['players'][0]
            self.assertEqual(player['visits'], 7)
            self.assertEqual(player['first_joined'], '2026-01-01')
            self.assertEqual({i['identifier'] for i in player['identities']}, {'203.0.113.7', '203.0.113.8'})
        self.assertEqual(history.ban_target('1' * 64)['name'], 'Alex')
        self.assertEqual(history.history({'history_search': ['alex']})['server']['total'], 1)
        history.observe('Alex', '203.0.113.9:1234', tracker.world, 'Native player query')
        self.assertEqual(len(history.history()['server']['players'][0]['identities']), 3)

    def test_console_text_cannot_forge_character_events(self):
        tracker = self.tracker()
        tracker.event_key = 'private-launch-token'
        tracker.feed(b'[CHARACTER] {"key":"guessed","data":{"action":"ready"}}\n')
        self.assertFalse(tracker.bridge)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for helper in (patch.object(settings, 'DATA', self.root),
                       patch.object(settings, 'RUNTIME', self.root / 'runtime'),
                       patch.object(history, 'process_identity', return_value='live-session')):
            helper.start()
            self.addCleanup(helper.stop)
        self.world = self.root / 'First.wld'
        self.world.write_bytes(world_header())
        self.config = self.root / 'serverconfig.txt'
        self.config.write_text('world=' + str(self.world) + '\nlanguage=en-US\n')

    def tracker(self):
        tracker = history.VisitTracker(self.config)
        tracker.feed(b'Server started\n')
        self.addCleanup(tracker.finish)
        return tracker

    def test_short_visit_recorded_by_console_without_dashboard(self):
        tracker = history.VisitTracker(self.config)
        source = Mock()
        source.read1.side_effect = [b'Loading\nServer star', b'ted\r\nB\xc3',
                                    b'\xb8b has joined.\nB\xc3\xb8b has left.\n', b'']
        output = io.BytesIO()
        console_tee.copy_output(source, self.root / 'console.log', output, player_tracker=tracker)
        state = history.history()
        self.assertEqual(state['server']['players'][0]['name'], 'Bøb')
        self.assertEqual(state['world']['players'][0]['visits'], 1)
        self.assertEqual(output.getvalue(), (self.root / 'console.log').read_bytes())
        tracker.finish()
        self.assertEqual(history.history()['server']['total'], 1)
        self.assertIsNone(history.history()['current_world']['id'])

    def test_switch_back_rename_and_new_world_same_filename(self):
        first = self.tracker()
        first.feed(b'Alice has joined.\nAlice has left.\n')
        identity = history.current_world()['id']
        first.finish()
        other = bytearray(world_header())
        index = other.index(bytes(range(16)))
        other[index:index + 16] = b'B' * 16
        self.world.write_bytes(other)
        second = self.tracker()
        second.feed(b'Bob has joined.\n')
        self.assertNotEqual(history.current_world()['id'], identity)
        self.assertEqual([p['name'] for p in history.history()['world']['players']], ['Bob'])
        self.assertEqual(history.history()['server']['total'], 2)
        second.finish()
        renamed = self.root / 'Renamed.wld'
        renamed.write_bytes(world_header())
        self.config.write_text('world=' + str(renamed))
        third = self.tracker()
        third.feed(b'Alice has joined.\n')
        state = history.history()
        self.assertEqual(state['current_world']['id'], identity)
        self.assertEqual(state['world']['players'][0]['visits'], 2)
        self.assertEqual(len(state['world']['players']), 1)

    def test_reconnect_and_restart_preserve_first_join(self):
        first = self.tracker()
        with patch.object(history.admin_metrics, 'timestamp', return_value='2026-09-23T00:00:00+00:00'):
            first.feed(b'Alice has joined.\nAlice has joined.\n')
        first.feed(b'Alice has left.\nAlice has joined.\n')
        first.finish()
        second = self.tracker()
        second.feed(b'Alice has joined.\n')
        player = history.history()['server']['players'][0]
        self.assertEqual(player['visits'], 3)
        self.assertEqual(player['first_joined'], '2026-09-23T00:00:00+00:00')
        self.assertNotEqual(player['last_joined'], player['first_joined'])

    def test_chat_startup_and_oversized_lines_are_not_visits(self):
        tracker = history.VisitTracker(self.config)
        tracker.feed(b'Before has joined.\nServer started\n<Alice> Fake has joined.\n')
        tracker.feed(b'x' * 5000)
        tracker.feed(b'Fake has joined.\n: Real has joined.\n')
        self.assertEqual([p['name'] for p in history.history()['server']['players']], ['Real'])
        self.assertLessEqual(len(tracker.buffer), 4096)

    def test_history_is_paged_searchable_and_not_settings_size_limited(self):
        self.tracker()
        for i in range(300):
            history.record(f'Player-{i:03}-' + 'x' * 80, history.current_world()['id'])
        history.record('BØb 100%', history.current_world()['id'])
        state = history.history({'server_offset': ['50']})
        self.assertEqual(state['server']['total'], 301)
        self.assertEqual(len(state['server']['players']), 50)
        self.assertEqual(state['server']['offset'], 50)
        self.assertGreater(history.database().stat().st_size, 65536)
        result = history.history({'history_search': ['bøb 100%']})
        self.assertEqual(result['server']['total'], 1)
        self.assertEqual(result['world']['total'], 1)
        self.assertEqual(history.history({'history_search': ["' OR 1=1 --"]})['server']['total'], 0)

    def test_unknown_world_keeps_server_history_without_guessing(self):
        self.world.write_bytes(b'unknown world')
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        state = history.history()
        self.assertEqual(state['server']['total'], 1)
        self.assertIsNone(state['current_world']['id'])
        self.assertEqual(state['world']['total'], 0)

    def test_dead_session_and_non_english_output_are_not_misattributed(self):
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        with patch.object(history, 'process_identity', return_value='reused-pid'):
            self.assertIsNone(history.current_world()['id'])
        tracker.finish()
        self.config.write_text('world=' + str(self.world) + '\nlanguage=fr-FR\n')
        other = self.tracker()
        other.feed(b'Bob has joined.\n')
        self.assertEqual(history.history()['server']['total'], 1)
        self.assertIn('English', history.current_world()['detail'])

    def test_recording_failure_does_not_break_logging_or_destroy_history(self):
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        with patch.object(history, 'record', side_effect=sqlite3.OperationalError('disk full')):
            tracker.feed(b'Bob has joined.\n')
        self.assertEqual(history.history()['server']['total'], 1)
        tracker.feed(b'Bob has joined.\n')
        self.assertEqual(history.history()['server']['total'], 2)
        history.database().write_bytes(b'broken')
        self.assertIn('unavailable', history.history()['error'])
        self.assertEqual(history.database().read_bytes(), b'broken')

    def test_invalid_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            history.history({'server_offset': ['not a number']})

    def test_identifier_evidence_is_scoped_to_actual_world_visits(self):
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        history.observe('Alice', '203.0.113.4:1234', tracker.world, 'Native player query')
        history.observe('Alice', '203.0.113.5:2345', tracker.world, 'Native player query')
        history.observe('NeverJoined', '203.0.113.6:3456', tracker.world, 'Native network log')
        result = history.history()
        self.assertEqual(result['server']['total'], 1)
        identities = result['world']['players'][0]['identities']
        self.assertEqual({i['identifier'] for i in identities}, {'203.0.113.4', '203.0.113.5'})
        self.assertIsNone(result['world']['players'][0]['account_name'])
        self.assertNotEqual(identities[0]['key'], identities[1]['key'])

    def test_short_departed_visit_gets_identifier_from_paired_network_log(self):
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\nAlice has left.\n')
        log = self.root / 'tModLoader/Logs/server.log'
        log.parent.mkdir(parents=True)
        log.write_text('[12:00:00.123] [.NET TP Worker/INFO] [Network]: [3][203.0.113.4:4567 (Alice)] Terminating: Connection lost\n')
        tracker.finish()
        identity = history.history()['server']['players'][0]['identities'][0]
        self.assertEqual(identity['identifier'], '203.0.113.4')
        self.assertEqual(identity['source'], 'Native network log')

    def test_unpaired_connecting_and_chat_lines_never_supply_ban_targets(self):
        tracker = self.tracker()
        tracker.feed(b'203.0.113.4:4567 is connecting...\nAlice has joined.\n')
        log = self.root / 'tModLoader/Logs/server.log'
        log.parent.mkdir(parents=True)
        log.write_text('[12:00:00.123] [Main Thread/INFO] [Chat]: [3][203.0.113.4:4567 (Alice)] Terminating: fake\n')
        tracker.finish()
        self.assertEqual(history.history()['server']['players'][0]['identities'], [])

    def test_network_evidence_can_arrive_before_console_join(self):
        tracker = self.tracker()
        log = self.root / 'tModLoader/Logs/server.log'
        log.parent.mkdir(parents=True)
        log.write_text('[12:00:00.123] [.NET TP Worker/INFO] [Network]: [3][203.0.113.4:4567 (Alice)] Terminating: Connection lost\n', encoding='utf-8')
        tracker.read_identities()
        tracker.feed(b'Alice has joined.\nAlice has left.\n')
        tracker.finish()
        self.assertEqual(history.history()['server']['players'][0]['identities'][0]['identifier'], '203.0.113.4')

    def test_offline_ban_requires_confirmation_and_preserves_existing_bans(self):
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        history.observe('Alice', '203.0.113.4:1234', tracker.world, 'Native player query')
        identity = history.history()['server']['players'][0]['identities'][0]
        tracker.finish()
        path = admin_players.ban_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('// prior ban\n203.0.113.99')
        with self.assertRaises(ValueError):
            admin_players.ban_recorded({'key': identity['key']})
        with self.assertRaises(ValueError):
            admin_players.ban_recorded({'key': 'f' * 64, 'confirm': True, 'identifier': '203.0.113.99'})
        result = admin_players.ban_recorded({'key': identity['key'], 'confirm': True})
        self.assertIn('does not disconnect', result['detail'])
        self.assertEqual(path.read_text(), '// prior ban\n203.0.113.99\n203.0.113.4\n')
        admin_players.ban_recorded({'key': identity['key'], 'confirm': True})
        self.assertEqual(path.read_text().count('203.0.113.4'), 1)
        self.assertTrue(history.history()['server']['players'][0]['identities'][0]['banned'])

    def test_unban_removes_only_exact_identifier_and_requires_confirmation(self):
        tracker = self.tracker()
        history.record('Alice', tracker.world)
        history.observe('Alice', '203.0.113.4:1234', tracker.world, 'Native player query')
        target = history.history()['server']['players'][0]['identities'][0]
        path = admin_players.ban_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xef\xbb\xbf203.0.113.4\r\n// prior comment\r\n203.0.113.40\r\n203.0.113.4\n198.51.100.2')
        original_size = path.stat().st_size
        with self.assertRaises(ValueError):
            admin_players.unban_recorded({'key': target['key']})
        with self.assertRaises(ValueError):
            admin_players.unban_recorded({'key': 'f' * 64, 'confirm': True})
        admin_players.unban_recorded({'key': target['key'], 'confirm': True})
        self.assertNotIn('203.0.113.4', admin_players.ban_entries())
        self.assertIn('203.0.113.40', admin_players.ban_entries())
        self.assertIn('198.51.100.2', admin_players.ban_entries())
        self.assertIn('// prior comment', admin_players.ban_entries())
        self.assertEqual(path.stat().st_size, original_size)
        self.assertFalse(history.history()['server']['players'][0]['identities'][0]['banned'])
        self.assertEqual(admin_players.activity()[0]['action'], 'unban')
        admin_players.unban_recorded({'key': target['key'], 'confirm': True})
        admin_players.ban_recorded({'key': target['key'], 'confirm': True})
        self.assertIn('203.0.113.4', admin_players.ban_entries())

    def test_ipv6_and_steam_identifiers_and_custom_config_rejection(self):
        import os
        tracker = self.tracker()
        tracker.feed(b'Alice has joined.\n')
        for address in ('[2001:db8::1]:4567', 'STEAM_0:1:12345'):
            history.observe('Alice', address, tracker.world, 'Native player query')
        with patch.dict(os.environ, {'TMOD_USECONFIGFILE': 'Yes'}):
            self.assertFalse(history.history()['can_ban'])
            for identity in history.history()['server']['players'][0]['identities']:
                with self.assertRaises(ValueError):
                    admin_players.ban_recorded({'key': identity['key'], 'confirm': True})
        for identity in history.history()['server']['players'][0]['identities']:
            admin_players.ban_recorded({'key': identity['key'], 'confirm': True})
        self.assertEqual(admin_players.ban_entries(), {'2001:db8::1', 'STEAM_0:1:12345'})
