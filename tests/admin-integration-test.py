"""Run against a local Docker engine using disposable Docker volumes."""
import json
import re
from pathlib import Path
import subprocess
import sys
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
try:
    backup.docker('run', '-d', '--name', name,
                  '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777',
                  '--cap-drop', 'ALL',
                  '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE',
                  '--cap-add', 'FOWNER', '--cap-add', 'SETGID', '--cap-add', 'SETUID',
                  '--security-opt', 'no-new-privileges:true',
                  '--volume', '/data', '--volume', '/backups',
                  '-p', '127.0.0.1::8080', '-e', 'TMOD_WEB_ENABLED=1',
                  '-e', 'TMOD_CONFIG_SOURCE=web', '-e', 'TMOD_WORLDSIZE=1',
                  '-e', 'TMOD_AUTOSAVE_INTERVAL=0', '-e', 'TMOD_PASS=test-password', image)
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

    deadline = time.monotonic() + 60
    while True:
        logs = backup.docker('logs', name)
        match = re.search(r'One-time setup code: (\S+)', logs)
        if match:
            break
        if time.monotonic() >= deadline:
            raise AssertionError('First-run setup did not start')
        time.sleep(1)
    backup.docker('exec', name, 'test', '!', '-e', '/tmp/tmodloader/server.pid')
    request = urllib.request.Request(base + '/', headers={'Host': 'localhost:8080'})
    with urllib.request.urlopen(request, timeout=15) as response:
        assert b'Create your admin token' in response.read()
    assert api('/api/setup', {'code': match.group(1), 'token': token, 'confirm': token}, authenticated=False)['ready']
    encoded = backup.docker('exec', name, 'cat', '/data/admin/token.argon2')
    assert encoded.startswith('$argon2id$')
    assert token not in encoded
    assert backup.docker('exec', name, 'stat', '-c', '%a', '/data/admin/token.argon2') == '600'
    print('Web setup saved a private Argon2id hash; waiting for game health.', flush=True)
    backup.wait_healthy(name, 600)
    print('First-boot game startup is healthy.', flush=True)

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
    old_world = Path('/data/tModLoader/Worlds') / (original['running']['TMOD_WORLDNAME'] + '.wld')
    backup.docker('exec', name, 'test', '-f', str(old_world).replace('\\', '/'))
    staged = api('/api/settings', {'revision': original['revision'], 'settings': {
        'TMOD_MAXPLAYERS': '5', 'TMOD_WORLDNAME': 'AdminCorruption', 'TMOD_WORLDEVIL': 'corruption'}})
    assert staged['running']['TMOD_MAXPLAYERS'] == '8'
    assert staged['staged']['TMOD_MAXPLAYERS'] == '5'
    api('/api/apply', {'confirm': True, 'revision': staged['revision']})
    job()
    applied_job = api('/api/status')['job']
    assert applied_job['stage'] == 'health' and applied_job['started'] and applied_job['finished']
    assert api('/api/settings')['running']['TMOD_MAXPLAYERS'] == '5'
    assert api('/api/settings')['running']['TMOD_WORLDEVIL'] == 'corruption'
    backup.docker('exec', name, 'test', '-f', str(old_world).replace('\\', '/'))
    backup.docker('exec', name, 'test', '-f', '/data/tModLoader/Worlds/AdminCorruption.wld')
    backup.docker('exec', name, 'test', '-f', '/data/tModLoader/Worlds/AdminCorruption.twld')
    backup.docker('exec', name, 'bash', '-c',
                  'grep -q "Creating world .*Evil: 0," /data/tModLoader/Logs/container-console.log')
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
    backup.docker('restart', name)
    backup.wait_healthy(name, 600)
    # Docker may assign a new ephemeral host port when restarting the container.
    info = json.loads(backup.docker('inspect', name))[0]
    port = info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
    base = f'http://127.0.0.1:{port}'
    assert api('/api/settings')['running']['TMOD_MAXPLAYERS'] == '5'
    assert backup.docker('exec', name, 'cat', '/data/admin/token.argon2') == encoded
    print('Web setup, persisted hash restart, authentication, staged apply, password preservation, backup/verify and low-space safety passed.', flush=True)
except Exception:
    subprocess.run(['docker', 'logs', '--tail', '100', name], check=False)
    subprocess.run(['docker', 'exec', name, 'bash', '-x', '/usr/local/bin/healthcheck'], check=False)
    subprocess.run(['docker', 'exec', name, 'tail', '-80', '/data/tModLoader/Logs/server.log'], check=False)
    raise
finally:
    backup.docker('rm', '-fv', name)
