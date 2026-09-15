import io
import os
import sys
from pathlib import Path
import unittest
import threading
import urllib.request
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_access as access
import admin_server as server


class AccessTests(unittest.TestCase):
    def setUp(self):
        helper = patch.dict(os.environ, {'TMOD_WEB_ORIGIN': '', 'TMOD_WEB_TRUSTED_PROXY': ''})
        helper.start()
        self.addCleanup(helper.stop)

    def env(self, source='192.168.1.2', **extra):
        return {'REMOTE_ADDR': source, 'wsgi.url_scheme': 'http',
                'HTTP_HOST': '192.168.1.10:8080', **extra}

    def test_rfc1918_boundaries_and_mapped_ipv4(self):
        for source in ('10.0.0.0', '10.255.255.255', '172.16.0.0', '172.31.255.255',
                       '192.168.0.0', '192.168.255.255', '127.0.0.1', '::1',
                       '::ffff:192.168.1.2'):
            with self.subTest(source=source):
                access.check_request(self.env(source))
        for source in ('9.255.255.255', '11.0.0.0', '172.15.255.255', '172.32.0.0',
                       '192.167.255.255', '192.169.0.0', '100.64.0.1', '169.254.1.1',
                       '0.0.0.0', '192.0.2.1', '8.8.8.8', 'fc00::1', 'fe80::1',
                       '2001:4860:4860::8888', '::ffff:8.8.8.8', '', 'invalid'):
            with self.subTest(source=source), self.assertRaises(PermissionError):
                access.check_request(self.env(source))

    def test_source_not_destination_or_configured_scheme(self):
        with patch.dict(os.environ, {'TMOD_WEB_ORIGIN': 'https://192.168.1.10:8080'}):
            with self.assertRaisesRegex(PermissionError, 'HTTPS'):
                access.check_request(self.env('8.8.8.8'))
        access.check_request(self.env('8.8.8.8', **{'wsgi.url_scheme': 'https'}))

    def test_browser_origin_and_rebinding(self):
        access.check_request(self.env(HTTP_HOST='192.168.1.10:8090', HTTP_ORIGIN='http://192.168.1.10:8090'))
        access.check_request(self.env(HTTP_HOST='[::1]:8080'))
        for extra in ({'HTTP_ORIGIN': 'https://evil.example'}, {'HTTP_ORIGIN': 'null'},
                      {'HTTP_HOST': 'evil.example:8080'}):
            with self.assertRaises(PermissionError):
                access.check_request(self.env(**extra))
        with patch.dict(os.environ, {'TMOD_WEB_ORIGIN': 'http://terraria.home:8080'}):
            access.check_request(self.env(HTTP_HOST='terraria.home:8080', HTTP_ORIGIN='http://terraria.home:8080'))

    def test_untrusted_forwarded_headers_cannot_claim_https_or_private_source(self):
        for headers in ({'HTTP_X_FORWARDED_PROTO': 'https'},
                        {'HTTP_X_FORWARDED_FOR': '192.168.1.2'},
                        {'HTTP_FORWARDED': 'for=192.168.1.2;proto=https'}):
            for source in ('8.8.8.8', '192.168.1.2'):
                with self.subTest(headers=headers, source=source), self.assertRaises(PermissionError):
                    access.check_request(self.env(source, **headers))

    def test_trusted_proxy_uses_original_source_and_requires_complete_headers(self):
        with patch.dict(os.environ, {'TMOD_WEB_TRUSTED_PROXY': '172.18.0.2'}):
            headers = {'HTTP_X_FORWARDED_FOR': '8.8.8.8', 'HTTP_X_FORWARDED_PROTO': 'https'}
            access.check_request(self.env('172.18.0.2', **headers))
            headers['HTTP_X_FORWARDED_PROTO'] = 'http'
            with self.assertRaisesRegex(PermissionError, 'HTTPS'):
                access.check_request(self.env('172.18.0.2', **headers))
            headers['HTTP_X_FORWARDED_FOR'] = '192.168.1.2'
            access.check_request(self.env('172.18.0.2', **headers))
            for invalid in ({}, {'HTTP_X_FORWARDED_FOR': '192.168.1.2'},
                            {'HTTP_X_FORWARDED_FOR': '192.168.1.2, 8.8.8.8', 'HTTP_X_FORWARDED_PROTO': 'https'},
                            {'HTTP_X_FORWARDED_FOR': '8.8.8.8', 'HTTP_X_FORWARDED_PROTO': 'https,http'}):
                with self.assertRaises(PermissionError):
                    access.check_request(self.env('172.18.0.2', **invalid))

    def test_public_http_denied_before_setup_or_api_dispatch(self):
        for path in ('/', '/setup.js', '/api/setup', '/api/settings'):
            env = self.env('8.8.8.8', PATH_INFO=path, REQUEST_METHOD='POST',
                           CONTENT_LENGTH='2', CONTENT_TYPE='application/json',
                           **{'wsgi.input': io.BytesIO(b'{}')})
            result = []
            with patch.object(server, 'setup_request') as setup, patch.object(server, 'api') as api:
                body = b''.join(server.application(env, lambda status, headers: result.append(status)))
                self.assertEqual(result, ['403 Forbidden'])
                self.assertIn(b'HTTPS', body)
                setup.assert_not_called()
                api.assert_not_called()

    def test_proxy_configuration_rejects_wildcards_and_networks(self):
        for value in ('*', '172.18.0.0/16', 'proxy.local'):
            with patch.dict(os.environ, {'TMOD_WEB_TRUSTED_PROXY': value}), self.assertRaises(ValueError):
                access.validate_config()

    def test_live_waitress_preserves_peer_and_validates_proxy_headers(self):
        from waitress import create_server
        with patch.object(server, 'TOKEN_HASH', ''), patch.dict(os.environ, {'TMOD_WEB_TRUSTED_PROXY': '127.0.0.1'}):
            http = create_server(server.application, host='127.0.0.1', port=0,
                                 clear_untrusted_proxy_headers=False)
            worker = threading.Thread(target=http.run, daemon=True)
            worker.start()
            try:
                url = 'http://127.0.0.1:' + str(http.effective_port) + '/'
                for client, proto, expected in (('192.168.1.2', 'http', 200),
                                                ('8.8.8.8', 'http', 403),
                                                ('8.8.8.8', 'https', 200)):
                    headers = {'X-Forwarded-For': client, 'X-Forwarded-Proto': proto}
                    request = urllib.request.Request(url, headers=headers)
                    try:
                        response = urllib.request.urlopen(request, timeout=5)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        self.assertEqual(response.status, expected)
                        if expected == 200:
                            self.assertIn(b'Create your admin token', response.read())
                # Even a private proxy peer cannot omit its original-client headers.
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(url, timeout=5)
                self.assertEqual(raised.exception.code, 403)
            finally:
                http.close()
                worker.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
