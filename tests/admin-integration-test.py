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
                  '-p', '127.0.0.1::8080',
                  '-e', 'TMOD_CONFIG_SOURCE=web', '-e', 'TMOD_AUTO_UPDATE=0', '-e', 'TMOD_WORLDSIZE=1',
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
    roster = api('/api/players')
    assert roster['available'] and roster['players'] == [], roster
    assert roster['can_ban']
    assert api('/api/players/announce', {'message': 'Dashboard player-management integration test', 'confirm': True})['detail']
    assert api('/api/players')['activity'][0]['action'] == 'announcement'
    backup.docker('exec', name, 'bash', '-c', 'grep -Fxq "banlist=/data/tModLoader/banlist.txt" /terraria-server/serverconfig.txt')
    print('Native player snapshot, announcement delivery, activity and persistent ban configuration passed.', flush=True)

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
    staged = api('/api/settings', {'revision': original['revision'], 'settings': {'TMOD_MAXPLAYERS': '5'}})
    worlds = api('/api/worlds')
    assert any(world['selected'] for world in worlds['worlds'])
    staged = api('/api/worlds/stage', {'revision': staged['revision'], 'action': 'create', 'name': 'AdminCorruption',
        'creation': {'TMOD_WORLDSIZE': '1', 'TMOD_DIFFICULTY': '1', 'TMOD_WORLDEVIL': 'corruption', 'TMOD_WORLDSEED': ''}})
    assert staged['running']['TMOD_MAXPLAYERS'] == '8'
    assert staged['staged']['TMOD_MAXPLAYERS'] == '5'
    api('/api/apply', {'confirm': True, 'revision': staged['revision']})
    job()
    applied_job = api('/api/status')['job']
    assert applied_job['stage'] == 'health' and applied_job['started'] and applied_job['finished']
    assert api('/api/settings')['running']['TMOD_MAXPLAYERS'] == '5'
    assert api('/api/settings')['running']['TMOD_WORLDEVIL'] == 'corruption'
    assert api('/api/worlds')['configured'] == 'AdminCorruption'
    world_settings = api('/api/settings')
    switched = api('/api/worlds/stage', {'revision': world_settings['revision'], 'action': 'switch', 'name': original['running']['TMOD_WORLDNAME']})
    api('/api/apply', {'confirm': True, 'revision': switched['revision']})
    job()
    assert api('/api/worlds')['configured'] == original['running']['TMOD_WORLDNAME']
    catalog = api('/api/playthroughs')
    catalog = api('/api/playthroughs', {'action': 'save', 'name': 'Adventure', 'source': 'running',
                                      'world': 'AdminCorruption', 'revision': catalog['revision'],
                                      'catalog_revision': catalog['catalog_revision']})
    switched = api('/api/playthroughs', {'action': 'stage', 'id': catalog['playthroughs'][0]['id'],
                                       'revision': catalog['revision'], 'catalog_revision': catalog['catalog_revision']})
    api('/api/apply', {'confirm': True, 'revision': switched['revision']})
    job()
    assert api('/api/settings')['running']['TMOD_WORLDNAME'] == 'AdminCorruption'
    print('World creation and saved playthrough switching passed.', flush=True)
    backup.docker('exec', name, 'test', '-f', str(old_world).replace('\\', '/'))
    backup.docker('exec', name, 'test', '-f', '/data/tModLoader/Worlds/AdminCorruption.wld')
    backup.docker('exec', name, 'test', '-f', '/data/tModLoader/Worlds/AdminCorruption.twld')
    backup.docker('exec', name, 'bash', '-c',
                  'grep -Rq "Creating world .*Evil: 0," /data/tModLoader/Logs')
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
    archive = state['backups']['archives'][0]['name']
    api('/api/recovery/preview', {'archive': archive})
    job()
    preview = api('/api/status')['job']['preview']
    assert 'AdminCorruption.wld' in preview['worlds']
    backup.docker('exec', name, 'touch', '/data/recovery-marker')
    pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
    api('/api/recovery/restore', {'archive': archive, 'sha256': '0' * 64, 'confirm': True})
    job('failed')
    assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') == pid
    api('/api/recovery/restore', {'archive': archive, 'sha256': preview['sha256'], 'confirm': True})
    job()
    assert api('/api/status')['healthy']
    assert api('/api/recovery')['originals']
    backup.docker('exec', name, 'test', '!', '-e', '/data/recovery-marker')
    retained = api('/api/recovery')['originals'][-1]
    backup.docker('exec', name, 'test', '-f', '/data/.tmod-control/' + retained + '/recovery-marker')
    assert backup.docker('exec', name, 'cat', '/data/admin/token.argon2') == encoded
    print('Recovery preview, changed-checksum rejection, live restore, original retention and authenticated health checks passed.', flush=True)
    # Force startup failure, then repair the disposable runner and retry through
    # the same dashboard that must remain available after failed recovery.
    backup.docker('exec', name, 'bash', '-c', 'cp run-server.sh /tmp/recovery-runner-original; printf "#!/bin/bash\\nexit 1\\n" > run-server.sh')
    api('/api/recovery/retry', {'confirm': True})
    job('failed')
    assert not api('/api/status')['healthy']
    backup.docker('exec', name, 'bash', '-c', 'cp /tmp/recovery-runner-original run-server.sh')
    api('/api/recovery/retry', {'confirm': True})
    job()
    assert api('/api/status')['healthy']
    print('Failed recovery startup leaves dashboard available; repaired startup retry passed.', flush=True)
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
    started = json.loads(backup.docker('inspect', name))[0]['State']['StartedAt']
    old_pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
    api('/api/updates/restart', {'confirm': True})
    job('success')
    assert api('/api/status')['healthy']
    assert json.loads(backup.docker('inspect', name))[0]['State']['StartedAt'] == started
    assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') != old_pid
    print('Dashboard runtime restart changed the game process, preserved container uptime and returned healthy.', flush=True)
    print('Web setup, persisted hash restart, authentication, staged apply, password preservation, backup/verify and low-space safety passed.', flush=True)
except Exception:
    subprocess.run(['docker', 'logs', '--tail', '100', name], check=False)
    subprocess.run(['docker', 'exec', name, 'bash', '-x', '/usr/local/bin/healthcheck'], check=False)
    subprocess.run(['docker', 'exec', name, 'tail', '-80', '/data/tModLoader/Logs/server.log'], check=False)
    raise
finally:
    backup.docker('rm', '-fv', name)
