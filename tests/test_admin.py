import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_server as server
import admin_settings as settings
import admin_metrics as metrics
import admin_workshop as workshop
import admin_schema
import console_tee
import filter_client_mods


class AdminTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in [('ACTIVE', self.root / 'settings.json'), ('PENDING', self.root / 'pending.json'), ('RUNTIME', self.root)]:
            helper = patch.object(settings, name, value)
            helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'web', 'TMOD_WEB_ORIGIN': 'http://localhost:8080', 'TMOD_MOTD': 'Original', 'TMOD_PASS': 'do-not-leak'})
        helper.start(); self.addCleanup(helper.stop)
        self.token = 'test-only-token-with-at-least-32-characters'
        server.TOKEN_HASH = server.admin_auth.HASHER.hash(self.token)
        server.JOB = {'state': 'idle'}
        helper = patch.object(metrics, 'STATE', self.root / 'backup-status.json')
        helper.start(); self.addCleanup(helper.stop)

    def request(self, path, body=None, auth=True, origin=None, host='localhost:8080'):
        encoded = json.dumps(body).encode() if body is not None else b''
        environ = {'REQUEST_METHOD': 'POST' if body is not None else 'GET', 'PATH_INFO': path,
                   'HTTP_HOST': host, 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(encoded)),
                   'wsgi.input': io.BytesIO(encoded)}
        if auth: environ['HTTP_AUTHORIZATION'] = 'Bearer ' + self.token
        if origin: environ['HTTP_ORIGIN'] = origin
        response = []
        body = b''.join(server.application(environ, lambda status, headers: response.append((status, headers))))
        return response[0][0], body

    def test_authentication_required(self):
        self.assertTrue(self.request('/api/settings', auth=False)[0].startswith('403'))

    def test_wrong_token_rejected(self):
        self.token = 'wrong-token-with-at-least-32-characters'
        self.assertTrue(self.request('/api/settings')[0].startswith('403'))

    def test_eight_character_token_boundary(self):
        self.token = 'Eight123'
        server.TOKEN_HASH = server.admin_auth.HASHER.hash(self.token)
        self.assertTrue(self.request('/api/settings')[0].startswith('200'))
        for value in ('Seven12', 'x' * 257, 'has space', 'nonasciié'):
            with self.assertRaises(ValueError):
                server.admin_auth.validate_token(value)

    def test_first_run_setup_is_code_protected_and_one_time(self):
        path = self.root / 'token.argon2'
        with patch.object(server, 'TOKEN_HASH', ''), patch.object(server, 'SETUP_CODE', 'one-time-code'), patch.object(server, 'SETUP_NEXT', 0), patch.object(server.admin_auth, 'token_path', return_value=path):
            payload = {'code': 'wrong', 'token': self.token, 'confirm': self.token}
            self.assertTrue(self.request('/api/setup', payload, auth=False)[0].startswith('403'))
            self.assertFalse(path.exists())
            server.SETUP_NEXT = 0
            payload['code'] = 'one-time-code'
            self.assertTrue(self.request('/api/setup', payload, auth=False, origin='https://evil.example')[0].startswith('403'))
            self.assertFalse(path.exists())
            payload['confirm'] = 'different'
            self.assertTrue(self.request('/api/setup', payload, auth=False)[0].startswith('400'))
            self.assertFalse(path.exists())
            server.SETUP_NEXT = 0
            payload['confirm'] = self.token
            self.assertTrue(self.request('/api/setup', payload, auth=False)[0].startswith('200'))
            self.assertNotIn(self.token, path.read_text())
            self.assertTrue(server.admin_auth.verify(server.admin_auth.read_hash(path), self.token))
            self.assertTrue((self.root / 'admin-auth-ready').exists())
            self.assertEqual(server.SETUP_CODE, '')
            self.assertTrue(self.request('/api/setup', payload, auth=False)[0].startswith('403'))
            self.assertTrue(self.request('/api/settings')[0].startswith('200'))

    def test_plaintext_and_malformed_hash_rejected(self):
        path = self.root / 'token.argon2'
        for value in (self.token, '$argon2id$v=19$invalid'):
            path.write_text(value)
            with self.assertRaises(ValueError):
                server.admin_auth.read_hash(path)

    def test_setup_page_and_saved_hash_restart(self):
        from types import SimpleNamespace
        path = self.root / 'token.argon2'
        with patch.object(server, 'TOKEN_HASH', ''):
            self.assertIn(b'Create your admin token', self.request('/', auth=False)[1])
        server.admin_auth.save_token(path, self.token)
        with patch.object(server.admin_auth, 'token_path', return_value=path), patch.dict(sys.modules, {'waitress': SimpleNamespace(serve=lambda *a, **kw: None)}):
            server.main()
        self.assertTrue((self.root / 'admin-auth-ready').exists())
        self.assertTrue(self.request('/api/settings')[0].startswith('200'))

    def test_remote_plain_http_setup_refused(self):
        with patch.object(server, 'TOKEN_HASH', ''), patch.object(server, 'SETUP_CODE', ''), patch.object(server.admin_auth, 'token_path', return_value=self.root / 'absent'), patch.dict(os.environ, {'TMOD_WEB_ORIGIN': 'http://example.com:8080'}):
            with self.assertRaisesRegex(ValueError, 'HTTPS'):
                server.main()

    def test_cross_origin_and_rebinding_rejected(self):
        self.assertTrue(self.request('/api/settings', origin='https://evil.example')[0].startswith('403'))
        self.assertTrue(self.request('/api/settings', host='evil.example')[0].startswith('403'))

    def test_secrets_not_returned(self):
        status, body = self.request('/api/settings')
        self.assertTrue(status.startswith('200'))
        self.assertNotIn(b'do-not-leak', body)
        self.assertNotIn(b'TMOD_PASS"', body)

    def test_stage_does_not_modify_active(self):
        current = server.configuration()
        status, body = self.request('/api/settings', {'revision': current['revision'], 'settings': {'TMOD_MOTD': 'Next'}})
        self.assertTrue(status.startswith('200'), body)
        self.assertEqual(settings.read_json(settings.PENDING)['TMOD_MOTD'], 'Next')
        self.assertFalse(settings.ACTIVE.exists())

    def test_stale_revision_rejected(self):
        status, _ = self.request('/api/settings', {'revision': 'old', 'settings': {'TMOD_MOTD': 'Next'}})
        self.assertTrue(status.startswith('400'))
        self.assertFalse(settings.PENDING.exists())

    def test_environment_mode_is_readonly(self):
        with patch.dict(os.environ, {'TMOD_CONFIG_SOURCE': 'env'}):
            self.assertTrue(self.request('/api/settings', {'settings': {}})[0].startswith('400'))

    def test_dangerous_settings_rejected(self):
        for value in ({'PATH': '/evil'}, {'TMOD_WORLDNAME': '../outside'}, {'TMOD_MOTD': 'x\npassword=bad'},
                      {'TMOD_MODS': '1; rm -rf /'}, {'TMOD_BACKUP_KEEP': '0'}, {'TMOD_PASS': 'secret'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.validate(value)

    def test_shell_exports_quote_metacharacters(self):
        result = settings.exports({'TMOD_MOTD': "$(touch /tmp/not-run); ' hello"})
        self.assertIn("export TMOD_MOTD='", result)

    def test_world_evil_choices_and_persistence(self):
        for evil in ('random', 'corruption', 'crimson'):
            self.assertEqual(settings.validate({'TMOD_WORLDEVIL': evil})['TMOD_WORLDEVIL'], evil)
        for evil in ('2', 'Crimson', '', 'both'):
            with self.assertRaises(ValueError):
                settings.validate({'TMOD_WORLDEVIL': evil})
        settings.atomic_json(settings.ACTIVE, {'TMOD_WORLDEVIL': 'crimson'})
        with patch.dict(os.environ, {'TMOD_WORLDEVIL': 'random'}):
            self.assertEqual(settings.boot_values()['TMOD_WORLDEVIL'], 'crimson')

    def test_action_requires_confirmation(self):
        with patch.object(server, 'start_job') as start:
            self.assertTrue(self.request('/api/backup', {})[0].startswith('400'))
            start.assert_not_called()

    def test_archive_traversal_rejected(self):
        with patch.object(server, 'start_job') as start:
            self.assertTrue(self.request('/api/verify', {'confirm': True, 'archive': 'tmod-backup-../../etc'})[0].startswith('400'))
            start.assert_not_called()

    def test_status_preserves_last_success_on_failure(self):
        with patch.object(metrics, 'STATE', self.root / 'status.json'):
            metrics.record('success', 'done')
            stamp = settings.read_json(metrics.STATE)['last_success']
            metrics.record('failed', 'disk full')
            self.assertEqual(settings.read_json(metrics.STATE)['last_success'], stamp)

    def test_backup_blocks_settings_edits(self):
        metrics.record('running', 'archiving')
        current = server.configuration()
        self.assertTrue(self.request('/api/settings', {'revision': current['revision'], 'settings': {'TMOD_MOTD': 'Next'}})[0].startswith('400'))

    def test_apply_requires_reviewed_revision(self):
        settings.atomic_json(settings.PENDING, {'TMOD_MOTD': 'Next'})
        with patch.object(server, 'start_job') as start:
            self.assertTrue(self.request('/api/apply', {'confirm': True, 'revision': 'old'})[0].startswith('400'))
            start.assert_not_called()

    def test_workshop_rejects_arbitrary_urls(self):
        with patch.object(workshop, 'steam') as steam:
            with self.assertRaises(ValueError): workshop.lookup('http://127.0.0.1/secrets')
            steam.assert_not_called()

    def test_every_setting_has_group_and_help(self):
        self.assertEqual(set(admin_schema.FIELDS), settings.KEYS)
        groups = {entry[0] for entry in admin_schema.GROUPS}
        for value in admin_schema.FIELDS.values():
            self.assertIn(value['group'], groups)
            self.assertTrue(value['label'])
            self.assertGreater(len(value['help']), 30)

    def test_console_requires_authentication(self):
        self.assertTrue(self.request('/api/console', auth=False)[0].startswith('403'))
        self.assertTrue(self.request('/api/console', {'command': 'help'}, auth=False)[0].startswith('403'))

    def test_console_rejects_multiline_and_empty_commands(self):
        for command in ['', ' ', 'save\nexit', 'say\rhello', 'x' * 4001, 'say\x00hello']:
            with self.subTest(command=command[:20]), patch.object(server.subprocess, 'run') as run:
                self.assertTrue(self.request('/api/console', {'command': command})[0].startswith('400'))
                run.assert_not_called()

    def test_console_uses_inject_without_a_shell(self):
        with patch.object(server, 'health', return_value=True), patch.object(server.subprocess, 'run') as run:
            run.return_value.returncode = 0
            status, _ = self.request('/api/console', {'command': 'say $(not-a-shell-command)'})
            self.assertTrue(status.startswith('200'))
            self.assertEqual(run.call_args.args[0], ['inject', 'say $(not-a-shell-command)'])
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_console_rejects_stop_without_confirmation(self):
        with patch.object(server.subprocess, 'run') as run:
            self.assertTrue(self.request('/api/console', {'command': 'exit-nosave'})[0].startswith('400'))
            run.assert_not_called()

    def test_console_blocks_commands_during_backup(self):
        metrics.record('running', 'archiving')
        with patch.object(server.subprocess, 'run') as run:
            self.assertTrue(self.request('/api/console', {'command': 'save'})[0].startswith('400'))
            run.assert_not_called()

    def test_console_tail_is_bounded_and_plain_text(self):
        log = self.root / 'console.log'
        log.write_text('\n'.join(f'<script>line {number}</script>' for number in range(10000)))
        with patch.object(server, 'CONSOLE_LOG', log):
            status, body = self.request('/api/console')
            output = json.loads(body)['output']
            self.assertTrue(status.startswith('200'))
            self.assertEqual(len(output.splitlines()), 200)
            self.assertIn('line 9999', output)
            self.assertLessEqual(len(output.encode()), 65536)

    def test_console_history_reads_all_pages_without_utf8_loss(self):
        log = self.root / 'console.log'
        content = 'x' * 65535 + '🌍' + '\nolder output\n' * 10000
        log.write_bytes(content.encode())
        offset, chunks = 0, []
        with patch.object(server, 'CONSOLE_LOG', log):
            while True:
                page = server.console_output({'mode': ['history'], 'offset': [str(offset)]})
                chunks.append(page['output'])
                self.assertLessEqual(len(page['output'].encode()), 65536)
                offset = page['next_offset']
                if page['done']: break
            self.assertEqual(''.join(chunks), content)
            for bad in ('-1', 'invalid', str(offset + 1)):
                with self.assertRaises(ValueError):
                    server.console_output({'mode': ['history'], 'offset': [bad]})

    def test_apply_progress_preserves_stage_and_timing(self):
        settings.atomic_json(settings.RUNTIME / 'supervisor.pid', 123)
        server.JOB = {'kind': 'apply', 'state': 'running', 'started': 'test-start'}
        def read(path, *args):
            if path.name == 'admin-progress':
                return {'id': 'test-request', 'stage': 'health', 'detail': 'Waiting for health'}
            if path.name == 'admin-result':
                return {'id': 'test-request', 'status': 0}
            return {}
        with patch.object(server.uuid, 'uuid4') as uid, patch.object(settings, 'read_json', side_effect=read), patch.object(server, 'OPERATION'):
            uid.return_value.hex = 'test-request'
            server.job_runner('apply')
        self.assertEqual(server.JOB['state'], 'success')
        self.assertEqual(server.JOB['stage'], 'health')
        self.assertEqual(server.JOB['started'], 'test-start')

    def test_history_source_and_rotation_checks(self):
        log = self.root / 'console.log'
        log.write_text('current')
        log.with_name('container-console.previous.log').write_text('previous')
        with patch.object(server, 'CONSOLE_LOG', log):
            self.assertEqual(server.console_output({'mode': ['history'], 'source': ['previous']})['output'], 'previous')
            with self.assertRaises(ValueError):
                server.console_output({'source': ['../../secret']})
            with self.assertRaises(ValueError):
                server.console_output({'mode': ['history'], 'identity': ['stale']})

    def test_timestamped_run_catalog_and_archive_reading(self):
        log = self.root / 'console.log'
        log.write_text('current')
        archive_dir = self.root / 'console-history'
        archive_dir.mkdir()
        archive = archive_dir / 'run-20260901T120000Z-Ab1234.log'
        archive.write_text('historical output')
        os.utime(archive, (1000, 1000))
        (archive_dir / 'unrelated.log').write_text('not exposed')
        with patch.object(server, 'CONSOLE_LOG', log):
            runs = server.console_sources()['runs']
            self.assertEqual([item['id'] for item in runs], ['current', archive.name])
            self.assertEqual(runs[1]['updated'], '1970-01-01T00:16:40+00:00')
            self.assertEqual(server.console_output({'mode': ['history'], 'source': [archive.name]})['output'], 'historical output')
            self.assertTrue(self.request('/api/console/runs', auth=False)[0].startswith('403'))

    def test_output_capture_preserves_bytes_and_records_first_time(self):
        log = self.root / 'console.log'
        output = b'first line\n\xfflast line\n'
        destination = io.BytesIO()
        console_tee.copy_output(io.BytesIO(output), log, destination)
        self.assertEqual(log.read_bytes(), output)
        self.assertEqual(destination.getvalue(), output)
        with patch.object(server, 'CONSOLE_LOG', log):
            run = server.console_sources()['runs'][0]
            self.assertIsNotNone(run['first'])
            self.assertLessEqual(run['first'], run['updated'])

    def test_workshop_requires_nonempty_readable_key(self):
        key = self.root / 'key'
        with patch.dict(os.environ, {'TMOD_WORKSHOP_KEY_FILE': str(key)}):
            self.assertFalse(workshop.key_available())
            key.write_text('  ')
            self.assertFalse(workshop.key_available())
            with patch.object(workshop, 'lookup') as lookup:
                lookup.return_value = {'id': '123', 'title': 'Example'}
                self.assertTrue(self.request('/api/workshop/lookup', {'value': '123'})[0].startswith('200'))
                lookup.assert_called_once_with('123')
            with self.assertRaises(ValueError):
                workshop.query('example')
            key.write_text('test-key')
            self.assertTrue(workshop.key_available())

    def test_running_mod_names_require_completed_loading_and_health(self):
        log = self.root / 'container-console.log'
        server_log = self.root / 'server.log'
        content = ('[Main Thread/INFO] [tML]: Finding Mods...\n'
                   '[Main Thread/INFO] [tML]: Finalizing Content: ModLoader (tModLoader) v1.0\n'
                   '[Main Thread/INFO] [tML]: Finalizing Content: TestMod (A Friendly Name) v2.3\n')
        with patch.object(server, 'CONSOLE_LOG', log):
            server_log.write_text(content)
            self.assertFalse(server.running_mods(True)['available'])
            server_log.write_text(content + '[Main Thread/INFO] [tML]: Mod Load Completed in 20ms\n')
            result = server.running_mods(True)
            self.assertEqual(result['mods'], [{'name': 'A Friendly Name', 'version': '2.3', 'internal_name': 'TestMod'}])
            self.assertFalse(server.running_mods(False)['available'])
            server_log.write_text(content + '[Main Thread/INFO] [tML]: Mod Load Completed in 20ms\n[Main Thread/INFO] [tML]: Unloading Mods...\n')
            self.assertFalse(server.running_mods(True)['available'])

    def test_workshop_lookup_filters_wrong_game(self):
        with patch.object(workshop, 'steam', return_value={'response': {'publishedfiledetails': [{'publishedfileid': '123', 'consumer_app_id': 1}]}}):
            with self.assertRaises(ValueError): workshop.lookup('123')

    def test_client_only_card_classification(self):
        item = {'consumer_app_id': 1281930, 'publishedfileid': '123', 'tags': [{'tag': 'Client'}]}
        self.assertTrue(workshop.card(item)['client_only'])
        self.assertFalse(workshop.card({**item, 'file_type': 2})['client_only'])
        self.assertFalse(workshop.card({**item, 'tags': []})['client_only'])
        self.assertFalse(workshop.card({**item, 'tags': ['Client', 'Both']})['client_only'])

    def test_web_defaults_persist_and_saved_empty_values_win(self):
        with patch.dict(os.environ, {'TMOD_MOTD': 'Initial', 'TMOD_MODS': ''}):
            first = settings.boot_values()
            self.assertEqual(first['TMOD_MOTD'], 'Initial')
        with patch.dict(os.environ, {'TMOD_MOTD': 'Changed compose', 'TMOD_MODS': '123'}):
            second = settings.boot_values()
            self.assertEqual(second['TMOD_MOTD'], 'Initial')
            self.assertEqual(second['TMOD_MODS'], '')

    def test_client_ids_removed_from_saved_selection_and_draft(self):
        metadata = self.root / 'steamMods/steamapps/workshop/content/1281930/123/workshop.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'Tags': ['Client']}))
        with patch.object(settings, 'DATA', self.root), patch.dict(os.environ, {'TMOD_MODS': '123,456,collection:789'}):
            self.assertEqual(settings.boot_values()['TMOD_MODS'], '456,collection:789')
            settings.atomic_json(settings.PENDING, {'TMOD_MODS': '123,456', 'TMOD_MOTD': 'Keep draft'})
            settings.main('snapshot')
            self.assertEqual(settings.read_json(settings.ACTIVE)['TMOD_MODS'], '456,collection:789')
            self.assertEqual(settings.read_json(settings.PENDING), {'TMOD_MODS': '456', 'TMOD_MOTD': 'Keep draft'})

    def test_client_removal_notice_records_names_and_scopes_to_apply(self):
        metadata = self.root / 'steamMods/steamapps/workshop/content/1281930/123/workshop.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'Tags': ['Client']}))
        (metadata.parent / 'ClientExample.tmod').write_bytes(b'cached')
        with patch.object(settings, 'DATA', self.root):
            current = server.configuration()
            status, _ = self.request('/api/settings', {'revision': current['revision'], 'settings': {'TMOD_MODS': '123'}})
            self.assertTrue(status.startswith('200'))
            self.assertEqual(settings.read_json(settings.PENDING.with_name('pending-removed.json'))['names'], ['ClientExample'])
        report = settings.RUNTIME / 'admin-removed'
        settings.atomic_json(report, {'id': 'new', 'names': []})
        with patch.dict(os.environ, {'TMOD_ADMIN_REQUEST_ID': 'old'}):
            settings.record_removed(['StaleMod'])
        self.assertEqual(settings.read_json(report)['names'], [])
        with patch.dict(os.environ, {'TMOD_ADMIN_REQUEST_ID': 'new'}):
            settings.record_removed(['ClientExample', 'ClientExample'])
        self.assertEqual(settings.read_json(report)['names'], ['ClientExample'])

    def test_client_filter_preserves_cache_and_unknown_mods(self):
        enabled = self.root / 'tModLoader/Mods/enabled.json'
        enabled.parent.mkdir(parents=True)
        enabled.write_text(json.dumps(['ClientMod', 'ServerMod', 'UnknownMod']))
        for identity, name, tags in [('1', 'ClientMod', ['Client']), ('2', 'ServerMod', ['Both'])]:
            directory = self.root / 'steamMods/steamapps/workshop/content/1281930' / identity
            directory.mkdir(parents=True)
            (directory / 'workshop.json').write_text(json.dumps({'Tags': tags}))
            (directory / (name + '.tmod')).write_bytes(b'cached')
        self.assertEqual(filter_client_mods.filter_enabled(self.root), ['ClientMod'])
        self.assertEqual(json.loads(enabled.read_text()), ['ServerMod', 'UnknownMod'])
        self.assertTrue((self.root / 'steamMods/steamapps/workshop/content/1281930/1/ClientMod.tmod').exists())
        self.assertEqual(filter_client_mods.filter_enabled(self.root), [])

    def test_workshop_search_uses_cache_and_correct_app(self):
        keyfile = self.root / 'steam-key'; keyfile.write_text('test-key')
        workshop.CACHE.clear()
        item = {'consumer_app_id': 1281930, 'publishedfileid': '123', 'title': 'Test mod', 'result': 1}
        with patch.dict(os.environ, {'TMOD_WORKSHOP_KEY_FILE': str(keyfile)}), patch.object(workshop, 'steam', return_value={'response': {'publishedfiledetails': [item], 'total': 1}}) as steam:
            self.assertEqual(workshop.query('test')['items'][0]['title'], 'Test mod')
            workshop.query('test')
            steam.assert_called_once()
            self.assertEqual(json.loads(steam.call_args.args[1]['input_json'])['appid'], 1281930)


if __name__ == '__main__': unittest.main()
