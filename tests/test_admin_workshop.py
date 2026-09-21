import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import admin_workshop as workshop


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = Path(self.directory.name) / 'key'
        self.key.write_text('a' * 32)
        self.environment = patch.dict(os.environ, {'TMOD_WORKSHOP_KEY_FILE': str(self.key),
                                                   'TMOD_DATA_DIR': self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        context = workshop.authenticated('test-admin-token')
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def item(self, identity, children=(), **extra):
        return {'publishedfileid': identity, 'consumer_appid': workshop.APP_ID,
                'result': 1, 'title': 'Mod ' + identity,
                'children': [{'publishedfileid': child} for child in children], **extra}

    def test_nested_dependencies_cycles_deduplication_and_client_only(self):
        graph = {'1': self.item('1', ['2', '3', '4']), '2': self.item('2', ['3', '5']),
                 '3': self.item('3', ['1', '5']), '4': self.item('4', ['6'], tags=[{'tag': 'Client'}]),
                 '5': self.item('5')}
        def steam(path, parameters):
            request = json.loads(parameters['input_json'])
            self.assertTrue(request['includechildren'])
            return {'response': {'publishedfiledetails': [graph[i] for i in request['publishedfileids']]}}
        with patch.object(workshop, 'steam', side_effect=steam):
            plan = workshop.dependencies('1')
        self.assertEqual([item['id'] for item in plan['items']], ['2', '3', '5'])
        self.assertEqual([item['id'] for item in plan['excluded']], ['4'])

    def test_unavailable_dependency_fails_closed(self):
        with patch.object(workshop, 'steam', side_effect=[
                {'response': {'publishedfiledetails': [self.item('1', ['2'])]}},
                {'response': {'publishedfiledetails': [{'publishedfileid': '2', 'result': 9}]}}]):
            with self.assertRaisesRegex(ValueError, 'No mods were added'):
                workshop.dependencies('1')

    def test_missing_key_is_explicitly_unchecked(self):
        self.key.unlink()
        with patch.object(workshop, 'steam') as steam:
            self.assertFalse(workshop.dependencies('1')['checked'])
            steam.assert_not_called()

    def test_invalid_id_never_calls_steam(self):
        with patch.object(workshop, 'steam') as steam:
            with self.assertRaises(ValueError):
                workshop.dependencies('https://example.com')
            steam.assert_not_called()

    def test_validated_key_is_private_and_overrides_mount(self):
        with patch.object(workshop, 'steam', return_value={'response': {'total': 0}}):
            result = workshop.save_key('b' * 32)
        self.assertEqual(result, {'saved': True})
        self.assertEqual(workshop.read_key(), 'b' * 32)
        self.assertEqual(self.key.read_text(), 'a' * 32)
        self.assertEqual(workshop.managed_key_path().parent.name, '.tmod-control')
        if os.name == 'posix':
            self.assertEqual(workshop.managed_key_path().stat().st_mode & 0o777, 0o600)

    def test_encryption_wrong_token_tampering_and_request_cleanup(self):
        with patch.object(workshop, 'steam', return_value={'response': {'total': 0}}):
            workshop.save_key('b' * 32)
        saved = workshop.managed_key_path().read_text()
        self.assertNotIn('b' * 32, saved)
        self.assertNotIn('test-admin-token', saved)
        with workshop.authenticated('wrong-token'):
            self.assertFalse(workshop.key_available())
            with self.assertRaisesRegex(ValueError, 'cannot be unlocked'):
                workshop.read_key()
        self.assertEqual(workshop.read_key(), 'b' * 32)
        with workshop.authenticated(''):
            with self.assertRaises(ValueError):
                workshop.read_key()
        envelope = json.loads(saved)
        envelope['ciphertext'] = 'invalid'
        workshop.managed_key_path().write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, 'cannot be unlocked'):
            workshop.read_key()

    def test_plaintext_migrates_atomically_on_authenticated_use(self):
        path = workshop.managed_key_path()
        path.parent.mkdir()
        path.write_text('b' * 32)
        self.assertEqual(workshop.read_key(), 'b' * 32)
        self.assertNotIn('b' * 32, path.read_text())
        self.assertEqual(workshop.read_key(), 'b' * 32)

    def test_authenticated_api_uses_request_token_and_cleans_up(self):
        import admin_server as server
        payload = json.dumps({'key': 'b' * 32}).encode()
        response = []
        with patch.object(server.admin_access, 'check_request'), patch.object(server.admin_auth, 'verify', return_value=True), patch.object(workshop, 'steam', return_value={'response': {'total': 0}}):
            body = server.application({'PATH_INFO': '/api/workshop/key', 'REQUEST_METHOD': 'POST',
                                       'HTTP_AUTHORIZATION': 'Bearer request-specific-token',
                                       'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(payload)),
                                       'wsgi.input': io.BytesIO(payload)},
                                      lambda status, headers: response.append(status))
        self.assertEqual(response, ['200 OK'])
        self.assertEqual(json.loads(body[0]), {'saved': True})
        self.assertEqual(workshop.CREDENTIAL.get(), 'test-admin-token')
        with self.assertRaises(ValueError):
            workshop.read_key()
        with workshop.authenticated('request-specific-token'):
            self.assertEqual(workshop.read_key(), 'b' * 32)

    def test_failed_validation_preserves_existing_key(self):
        for response in ({}, {'response': {'result': 2}}):
            with patch.object(workshop, 'steam', return_value=response):
                with self.assertRaises(ValueError):
                    workshop.save_key('b' * 32)
            self.assertFalse(workshop.managed_key_path().exists())
            self.assertEqual(workshop.read_key(), 'a' * 32)

    def test_bad_key_format_does_not_contact_steam(self):
        with patch.object(workshop, 'steam') as steam:
            for value in (None, {}, 'short', 'z' * 32):
                with self.assertRaises(ValueError):
                    workshop.save_key(value)
            steam.assert_not_called()

    def test_saved_key_is_excluded_from_backup_archive(self):
        import backup
        with patch.object(workshop, 'steam', return_value={'response': {'total': 0}}):
            workshop.save_key('b' * 32)
        with tempfile.TemporaryDirectory() as destination:
            bundle = backup.create_backup(Path(self.directory.name), Path(destination),
                                          {'Image': 'test', 'Config': {'Image': 'test'}})
            with tarfile.open(bundle / 'data.tar.gz') as archive:
                self.assertFalse(any('.tmod-control' in name for name in archive.getnames()))

    def test_workshop_write_routes_require_authentication(self):
        import admin_server as server
        for path in ('/api/workshop/key', '/api/workshop/dependencies'):
            response = []
            with patch.object(server.admin_access, 'check_request'), patch.object(server.admin_auth, 'verify', return_value=False):
                server.application({'PATH_INFO': path, 'REQUEST_METHOD': 'POST'},
                                   lambda status, headers: response.append(status))
            self.assertEqual(response, ['403 Forbidden'])


if __name__ == '__main__':
    unittest.main()
