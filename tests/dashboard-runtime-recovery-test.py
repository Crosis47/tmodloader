"""Real dashboard runtime recovery without restarting the container; disposable data only."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup

image = sys.argv[1]
name = 'tmod-dashboard-recovery-' + uuid.uuid4().hex[:10]
volume = name + '-data'
token = uuid.uuid4().hex


def api(path, payload=None):
    info = json.loads(backup.docker('inspect', name))[0]
    port = info['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
    request = urllib.request.Request('http://127.0.0.1:' + port + path,
                                    headers={'Host': 'localhost:8080', 'Authorization': 'Bearer ' + token,
                                             'Content-Type': 'application/json'},
                                    data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


try:
    backup.docker('volume', 'create', volume)
    backup.docker('run', '--rm', '--volume', volume + ':/data', '--entrypoint', 'python3', image,
                  '-c', 'import admin_auth as a; a.save_token(a.token_path(), ' + repr(token) + ')')
    backup.docker('run', '-d', '--name', name, '--volume', volume + ':/data',
                  '-p', '127.0.0.1::8080', '-e', 'TMOD_AUTO_UPDATE=0', '-e', 'TMOD_WORLDSIZE=1',
                  '-e', 'TMOD_AUTOSAVE_INTERVAL=0', image)
    backup.wait_healthy(name, 600)
    backup.docker('stop', '--time', '120', name)
    # Create the fixture checkpoint cold, just as the production supervisor does.
    backup.docker('run', '--rm', '--volume', volume + ':/data', '--entrypoint', 'python3', image,
                  '-c', 'import runtime_updates as r, admin_updates as u, admin_settings as s; '
                        'r.boot(); r.cache_bundled(); identity, directory=r.snapshot(); '
                        's.atomic_json(u.ROOT / "checkpoint.json", {"id":identity}); '
                        '(s.DATA / "tModLoader/ModConfigs/after-checkpoint.json").parent.mkdir(parents=True, exist_ok=True); '
                        '(s.DATA / "tModLoader/ModConfigs/after-checkpoint.json").write_text("{}")')
    backup.docker('start', name)
    backup.wait_healthy(name, 600)
    started = json.loads(backup.docker('inspect', name))[0]['State']['StartedAt']
    pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
    api('/api/updates/rollback', {'confirm': True})
    api('/api/updates/restart', {'confirm': True})
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = api('/api/status')  # Authenticated dashboard stays responsive throughout.
        if state['job']['state'] != 'running':
            assert state['job']['state'] == 'success', state['job']
            assert state['healthy'], state
            break
        time.sleep(1)
    else:
        raise AssertionError('Dashboard recovery timed out')
    assert json.loads(backup.docker('inspect', name))[0]['State']['StartedAt'] == started
    assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') != pid
    updates = api('/api/updates')
    assert updates['hold'] and not updates['rollback_pending'], updates
    assert not updates['rollback_available'], updates
    backup.docker('exec', name, 'test', '!', '-e', '/data/.tmod-control/updates/recovery-cleanup.json')
    backup.docker('exec', name, 'test', '!', '-e', '/data/tModLoader/ModConfigs/after-checkpoint.json')
    print('Dashboard recovery restored checkpoint data, kept the container and dashboard running, and validated game health.', flush=True)
finally:
    if sys.exc_info()[0]:
        subprocess.run(['docker', 'logs', '--tail', '80', name], check=False)
    subprocess.run(['docker', 'rm', '--force', '--volumes', name], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
