"""Run against a local Docker engine; only disposable bind-mounted data is used."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backup

image = sys.argv[1]
name = 'tmod-admin-test-' + uuid.uuid4().hex[:12]
token = uuid.uuid4().hex + uuid.uuid4().hex
with tempfile.TemporaryDirectory(prefix='tmod-admin-integration-') as temp:
    root = Path(temp)
    for directory in ('data', 'backups'):
        (root / directory).mkdir()
        if hasattr(os, 'chown'):
            os.chown(root / directory, 1000, 1000)
    secret = root / 'token'
    secret.write_text(token)
    secret.chmod(0o600)
    if hasattr(os, 'chown'):
        os.chown(secret, 1000, 1000)
    try:
        backup.docker('run', '-d', '--name', name,
                      '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                      '--mount', f'type=bind,source={root / "data"},target=/data',
                      '--mount', f'type=bind,source={root / "backups"},target=/backups',
                      '--mount', f'type=bind,source={secret},target=/run/secrets/admin-token,readonly',
                      '-p', '127.0.0.1::8080', '-e', 'TMOD_WEB_ENABLED=1',
                      '-e', 'TMOD_WEB_TOKEN_FILE=/run/secrets/admin-token',
                      '-e', 'TMOD_CONFIG_SOURCE=web', '-e', 'TMOD_WORLDSIZE=1',
                      '-e', 'TMOD_AUTOSAVE_INTERVAL=0', '-e', 'TMOD_PASS=test-password', image)
        backup.wait_healthy(name, 600)
        info = json.loads(backup.docker('inspect', name))[0]
        port = info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
        base = f'http://127.0.0.1:{port}'

        def api(path, data=None, authenticated=True):
            headers = {'Host': 'localhost:8080', 'Content-Type': 'application/json'}
            if authenticated:
                headers['Authorization'] = 'Bearer ' + token
            request = urllib.request.Request(base + path, headers=headers,
                                             data=json.dumps(data).encode() if data is not None else None)
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)

        def job(expected='success'):
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                result = api('/api/status')['job']
                if result['state'] != 'running':
                    assert result['state'] == expected, result
                    return
                time.sleep(2)
            raise AssertionError('Admin operation timed out')

        try:
            api('/api/settings', authenticated=False)
            raise AssertionError('Unauthenticated request was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        original = api('/api/settings')
        assert original['groups'] and original['fields']['TMOD_BACKUP_KEEP']['help']
        assert api('/api/console')['available']
        history = api('/api/console?mode=history&offset=0')
        assert history['available'] and history['next_offset'] > 0
        assert api('/api/console', {'command': 'help'})['sent']
        deadline = time.monotonic() + 15
        while 'exit-nosave' not in api('/api/console')['output']:
            if time.monotonic() > deadline:
                raise AssertionError('Console did not show the help command response')
            time.sleep(1)
        assert 'test-password' not in json.dumps(original)
        staged = api('/api/settings', {'revision': original['revision'], 'settings': {'TMOD_MAXPLAYERS': '5'}})
        assert staged['running']['TMOD_MAXPLAYERS'] == '8'
        assert staged['staged']['TMOD_MAXPLAYERS'] == '5'
        api('/api/apply', {'confirm': True, 'revision': staged['revision']})
        job()
        applied_job = api('/api/status')['job']
        assert applied_job['stage'] == 'health' and applied_job['started'] and applied_job['finished']
        assert api('/api/settings')['running']['TMOD_MAXPLAYERS'] == '5'
        # Frequent dashboard reads must not consume anonymous player slots.
        for _ in range(20):
            assert api('/api/status')['healthy'], 'Readiness polling disrupted the game listener'
        backup.docker('exec', name, 'bash', '-c', 'grep -Fxq "password=test-password" /terraria-server/serverconfig.txt')
        api('/api/backup', {'confirm': True})
        job()
        state = api('/api/status')
        assert state['backups']['operation']['last_success']
        assert state['backups']['count'] == 1
        api('/api/verify', {'confirm': True, 'archive': state['backups']['archives'][0]['name']})
        job()
        # An impossible reserve must reject backup before the game is stopped.
        current = api('/api/settings')
        staged = api('/api/settings', {'revision': current['revision'], 'settings': {'TMOD_BACKUP_MIN_FREE_MB': '999999999'}})
        api('/api/apply', {'confirm': True, 'revision': staged['revision']})
        job()
        pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
        api('/api/backup', {'confirm': True})
        job('failed')
        assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') == pid
        deadline = time.monotonic() + 30
        while not api('/api/status')['healthy']:
            if time.monotonic() > deadline:
                raise AssertionError('Game did not remain healthy after low-space rejection')
            time.sleep(2)
        print('Admin authentication, staged apply, password preservation, backup/verify and low-space safety passed.')
    except Exception:
        subprocess.run(['docker', 'logs', '--tail', '100', name], check=False)
        subprocess.run(['docker', 'exec', name, 'bash', '-x', '/usr/local/bin/healthcheck'], check=False)
        subprocess.run(['docker', 'exec', name, 'tail', '-80', '/data/tModLoader/Logs/server.log'], check=False)
        raise
    finally:
        backup.docker('rm', '-f', name)
