import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_players as players
import admin_settings as settings

FRAME = ': Terraria Server v1.4.4.9 - tModLoader v2026.7.3.0\n'


class PlayerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key in ('DATA', 'RUNTIME'):
            helper = patch.object(settings, key, self.root)
            helper.start(); self.addCleanup(helper.stop)
        players.CACHE = None

    def test_empty_and_named_rosters(self):
        self.assertEqual(players.parse_roster(FRAME + ': No players connected.\n' + FRAME), [])
        result = players.parse_roster(FRAME + ': Alice (Builder) (127.0.0.1:4321)\nBøb ([::1]:4567)\nSteam (STEAM_0:1:234)\n3 players connected.\n' + FRAME)
        self.assertEqual([p['name'] for p in result], ['Alice (Builder)', 'Bøb', 'Steam'])
        self.assertEqual(result[1]['identifier'], '::1')
        self.assertTrue(all(p['can_moderate'] for p in result))

    def test_ambiguous_names_disable_moderation(self):
        result = players.parse_roster(FRAME + ': Alice (127.0.0.1:1)\nalice (127.0.0.1:2)\n2 players connected.\n' + FRAME)
        self.assertFalse(any(p['can_moderate'] for p in result))

    def test_missing_frame_or_partial_output_is_not_empty(self):
        self.assertIsNone(players.parse_roster(': No players connected.\n'))
        self.assertIsNone(players.parse_roster(FRAME + ': Alice (127.0.0.1:1)\n'))

    def test_interleaved_output_bad_address_and_wrong_count_rejected(self):
        for body in (': Alice (not-an-address)\n1 player connected.\n', ': Alice (127.0.0.1:1)\n2 players connected.\n', ': No players connected.\nchat message\n'):
            with self.assertRaises(ValueError):
                players.parse_roster(FRAME + body + FRAME)

    def test_snapshot_reads_only_fresh_output_and_caches_per_run(self):
        log = self.root / 'console.log'
        log.write_text(FRAME + ': Stale (127.0.0.1:1)\n1 player connected.\n' + FRAME)
        log.with_name('console.log.first').write_text('first-run')
        (self.root / 'server.pid').write_text('123')
        def reply(command):
            with log.open('a') as stream:
                stream.write(FRAME if command == 'version' else ': No players connected.\n')
        with patch.object(players, 'deliver', side_effect=reply) as deliver:
            result = players.snapshot(log)
            self.assertEqual(result['players'], [])
            players.snapshot(log)
            self.assertEqual(deliver.call_count, 3)
            log.with_name('console.log.first').write_text('next-run')
            players.snapshot(log)
            self.assertEqual(deliver.call_count, 6)

    def test_changed_connection_is_not_targeted(self):
        with patch.object(players, 'snapshot', return_value={'players': []}), patch.object(players, 'deliver') as send:
            with self.assertRaisesRegex(ValueError, 'left, reconnected'):
                players.moderate(None, {'action': 'kick', 'key': 'old', 'confirm': True})
            send.assert_not_called()

    def test_kick_exact_name_and_confirm_departure(self):
        player = {'name': 'A; $(name)', 'key': 'key', 'address': '127.0.0.1:1', 'identifier': '127.0.0.1', 'can_moderate': True}
        with patch.object(players, 'snapshot', side_effect=[{'players': [player]}, {'players': []}]), patch.object(players, 'deliver') as send:
            result = players.moderate(None, {'action': 'kick', 'key': 'key', 'confirm': True})
            send.assert_called_once_with('kick A; $(name)')
            self.assertIn('no longer connected', result['detail'])
        self.assertEqual(len(players.activity()), 2)

    def test_ban_reports_unconfirmed_persistence_honestly(self):
        player = {'name': 'Alice', 'key': 'key', 'address': '127.0.0.1:1', 'identifier': '127.0.0.1', 'can_moderate': True}
        with patch.object(players, 'snapshot', side_effect=[{'players': [player]}, {'players': []}]), patch.object(players, 'deliver'):
            result = players.moderate(None, {'action': 'ban', 'key': 'key', 'confirm': True})
        self.assertIn('persistence was not confirmed', result['detail'])

    def test_confirm_and_control_character_validation(self):
        with self.assertRaises(ValueError):
            players.moderate(None, {'action': 'kick', 'key': 'x'})
        for value in ('', 'say\nexit', 'x\rban', '\0', 'x' * 501):
            with self.assertRaises(ValueError):
                players.line_text(value)

    def test_audit_is_bounded_even_for_unicode_messages(self):
        for _ in range(55):
            players.audit('announcement', '界' * 500, 'Delivered')
        result = players.activity()
        self.assertLessEqual(len(result), 50)
        self.assertLessEqual(len(json.dumps(result).encode()), 60000)
