"""Readiness stays separate from game readiness and authenticated API access."""
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_access
import admin_server
import backup


class ReadinessTests(unittest.TestCase):
    def request(self, source='127.0.0.1', **extra):
        response = []
        env = {'REMOTE_ADDR': source, 'PATH_INFO': '/healthz', 'REQUEST_METHOD': 'GET',
               'HTTP_HOST': '127.0.0.1:30504', 'wsgi.url_scheme': 'http',
               'wsgi.input': io.BytesIO(), **extra}
        body = b''.join(admin_server.application(env, lambda status, headers: response.append(status)))
        return response[0], body

    def test_ready_before_setup_even_with_external_origin(self):
        with patch.object(admin_server, 'TOKEN_HASH', ''), \
                patch.dict(os.environ, {'TMOD_WEB_ORIGIN': 'https://dashboard.example.com',
                                        'TMOD_WEB_TRUSTED_PROXY': '127.0.0.1'}), \
                patch.object(admin_server, 'health', side_effect=AssertionError('Must not query game')):
            self.assertEqual(self.request(), ('200 OK', b'ok'))
            self.assertEqual(self.request('::1'), ('200 OK', b'ok'))

    def test_configured_dashboard_requires_game_readiness(self):
        with patch.object(admin_server, 'TOKEN_HASH', 'configured'):
            for ready, expected in [(False, ('503 Service Unavailable', b'unavailable')),
                                    (True, ('200 OK', b'ok'))]:
                with self.subTest(ready=ready), patch.object(admin_server, 'health', return_value=ready):
                    self.assertEqual(self.request(), expected)

    def test_readiness_rejects_remote_forwarded_and_mutating_requests(self):
        for source, extra in [('192.168.1.5', {}), ('127.0.0.1', {'REQUEST_METHOD': 'POST'}),
                              ('127.0.0.1', {'HTTP_X_FORWARDED_FOR': '127.0.0.1'}),
                              ('127.0.0.1', {'HTTP_FORWARDED': 'for=127.0.0.1'})]:
            with self.subTest(source=source, extra=extra):
                self.assertEqual(self.request(source, **extra)[0], '403 Forbidden')

    def test_listening_port_validation(self):
        for value in ('1', '8080', '30504', '65535'):
            with patch.dict(os.environ, {'TMOD_WEB_PORT': value}):
                self.assertEqual(admin_access.web_port(), int(value))
        for value in ('', '0', '65536', '-1', '1.5', ' 8080', 'abc', 'ï¼‘ï¼’ï¼“'):
            with self.subTest(value=value), patch.dict(os.environ, {'TMOD_WEB_PORT': value}):
                with self.assertRaisesRegex(ValueError, 'TMOD_WEB_PORT'):
                    admin_access.validate_config()

    def test_restore_waits_for_game_even_when_container_is_healthy(self):
        from types import SimpleNamespace
        state = '[{"State":{"Running":true,"Health":{"Status":"healthy"}}}]'
        with patch.object(backup, 'docker', return_value=state), \
                patch.object(backup.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1),
                                                                  SimpleNamespace(returncode=0)]) as probe, \
                patch.object(backup.time, 'sleep') as sleep:
            backup.wait_healthy('test', 10)
            self.assertEqual(probe.call_count, 2)
            sleep.assert_called_once_with(2)
            self.assertEqual(probe.call_args.args[0], ['docker', 'exec', 'test', 'healthcheck'])


if __name__ == '__main__':
    unittest.main()
