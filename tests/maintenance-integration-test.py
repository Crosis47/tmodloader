"""Disposable real-game test for maintenance controls; requires local Docker."""
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup

name = 'tmod-maintenance-test-' + uuid.uuid4().hex[:12]
token = uuid.uuid4().hex + uuid.uuid4().hex


def wait_for(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value: return value
        time.sleep(1)
    raise AssertionError('Timed out waiting for maintenance operation')


try:
    backup.docker('run', '-d', '--name', name, '--volume', '/data', '--volume', '/backups',
                  '-p', '127.0.0.1::8080', '-e', 'TMOD_CONFIG_SOURCE=web', '-e', 'TMOD_AUTO_UPDATE=0',
                  '-e', 'TMOD_WORLDSIZE=1', '-e', 'TMOD_AUTOSAVE_INTERVAL=0',
                  '-e', 'TMOD_RESTART_DELAY=5', '-e', 'TMOD_RESTART_COUNTDOWN=4,2', sys.argv[1])
    port = json.loads(backup.docker('inspect', name))[0]['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']

    def api(path, data=None, auth=True):
        headers = {'Host': 'localhost:8080', 'Content-Type': 'application/json'}
        if auth: headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(f'http://127.0.0.1:{port}' + path, headers=headers,
                                         data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=20) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            raise AssertionError(f'{path}: {error.code} {error.read().decode()}') from error

    code = wait_for(lambda: re.search(r'One-time setup code: (\S+)', backup.docker('logs', name)), 600).group(1)
    api('/api/setup', {'code': code, 'token': token, 'confirm': token}, auth=False)
    backup.wait_healthy(name, 600)
    print('Disposable game is healthy; testing save delivery and world write.', flush=True)

    def world_stamp():
        return backup.docker('exec', name, 'python3', '-c',
                             "from pathlib import Path; print(next(Path('/data/tModLoader/Worlds').glob('*.wld')).stat().st_mtime_ns)")

    old_stamp = world_stamp()
    assert api('/api/server/save', {})['sent']
    wait_for(lambda: world_stamp() != old_stamp)
    old_pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
    api('/api/server/restart', {'confirm': True})
    wait_for(lambda: api('/api/status')['restart_schedule'].get('state') == 'countdown')
    api('/api/restart/control', {'confirm': True, 'action': 'postpone', 'minutes': 15})
    wait_for(lambda: api('/api/status')['job']['state'] != 'running')
    api('/api/restart/control', {'confirm': True, 'action': 'skip'})
    assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') == old_pid
    print('Countdown postponed and canceled without stopping the game.', flush=True)

    settings = api('/api/settings')
    api('/api/settings', {'revision': settings['revision'], 'settings': {'TMOD_MOTD': 'Unapplied draft'}})
    api('/api/server/restart', {'confirm': True})
    wait_for(lambda: api('/api/status')['job']['state'] != 'running', 600)
    assert api('/api/status')['job']['state'] == 'success', api('/api/status')['job']
    assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') != old_pid
    settings = api('/api/settings')
    assert settings['pending'] and settings['running']['TMOD_MOTD'] != 'Unapplied draft'
    assert 'Server restarting in' in backup.docker('exec', name, 'cat', '/data/tModLoader/Logs/container-console.previous.log')
    print('Countdown restart saved the game, passed health, and preserved the draft.', flush=True)

    api('/api/settings', {'revision': settings['revision'], 'settings': {
        'TMOD_BACKUP_MODE': 'monthly', 'TMOD_BACKUP_MONTHDAY': '31', 'TMOD_BACKUP_TIMEZONE': 'UTC'}})
    api('/api/apply', {'confirm': True, 'revision': api('/api/settings')['revision']})
    wait_for(lambda: api('/api/status')['job']['state'] != 'running', 600)
    assert api('/api/status')['job']['state'] == 'success'
    assert api('/api/status')['backup_schedule']['mode'] == 'monthly'
    # Advance only the disposable schedule's due timestamp, avoiding a month-long wait.
    backup.docker('exec', '--user', 'tml:tml', name, 'python3', '-c',
                  "import time, admin_settings as s; p=s.RUNTIME/'backup-schedule.json'; v=s.read_json(p); v['next_at']=time.time()-1; s.atomic_json(p,v)")
    wait_for(lambda: api('/api/status')['backups']['operation'].get('state') == 'success', 600)
    state = api('/api/status')
    assert state['healthy'] and state['backups']['count'] >= 1
    assert state['backup_schedule']['next_at'] > time.time()
    print('Calendar backup ran, produced an archive, restarted healthy, and scheduled its next occurrence.', flush=True)
except Exception:
    print(backup.docker('logs', '--tail', '60', name), flush=True)
    raise
finally:
    try:
        backup.docker('rm', '-f', '-v', name)
    except Exception:
        pass
