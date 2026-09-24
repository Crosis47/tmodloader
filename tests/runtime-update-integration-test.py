"""Opt-in real upstream upgrade/rollback test with disposable Docker volumes.

Pass the image and an older supported stable release tag to install on first boot.
"""
import json
import subprocess
import sys
import time
import uuid

image = sys.argv[1]
initial_version = sys.argv[2]
name = 'tmod-update-test-' + uuid.uuid4().hex[:10]
volume = name + '-data'


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and result.returncode:
        raise RuntimeError(result.stdout)
    return result.stdout.strip()


def start(automatic):
    docker('run', '-d', '--name', name, '--volume', volume + ':/data',
           '-e', 'TMOD_WEB_ENABLED=0', '-e', 'TMOD_AUTOSAVE_INTERVAL=0', '-e', 'TMOD_WORLDSIZE=1',
           '-e', 'TMOD_AUTO_UPDATE=' + automatic,
           '-e', 'TMOD_UPDATE_VERSION=' + (initial_version if automatic == '0' else ''), image)


def stop():
    docker('stop', '--time', '90', name)
    docker('rm', name)


def read(path):
    return json.loads(docker('exec', name, 'cat', path))


def healthy():
    deadline = time.monotonic() + 720
    while time.monotonic() < deadline:
        info = json.loads(docker('inspect', name))[0]['State']
        if not info['Running']:
            raise RuntimeError(docker('logs', name))
        if info.get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(3)
    raise RuntimeError('Startup timed out:\n' + docker('logs', name))


try:
    docker('volume', 'create', volume)
    start('0')
    healthy()
    old = read('/data/.tmod-control/updates/active.json')['tmodloader_version']
    print('Original real server is healthy: ' + old, flush=True)
    stop()
    start('1')
    healthy()
    state = read('/data/.tmod-control/updates/status.json')
    assert state['state'] == 'updated', state
    active = read('/data/.tmod-control/updates/active.json')['tmodloader_version']
    assert active != old, (active, old)
    assert docker('exec', name, 'python3', '-c', "from pathlib import Path; print(Path('/data/.tmod-control/updates/journal.json').exists())") == 'False'
    print('Real startup upgrade passed copied-world validation and live readiness: ' + active, flush=True)
    checkpoint = read('/data/.tmod-control/updates/checkpoint.json')['id']
    saved = read('/data/.tmod-control/updates/transactions/' + checkpoint + '/manifest.json')
    assert saved['runtime']['tmodloader_version'] == old
    docker('exec', name, 'python3', '-c', "from pathlib import Path; Path('/data/.tmod-control/updates/rollback-request.json').write_text('{}')")
    stop()
    start('1')
    healthy()
    assert read('/data/.tmod-control/updates/active.json')['tmodloader_version'] == old
    assert read('/data/.tmod-control/updates/hold.json')['version'] == old
    assert read('/data/.tmod-control/updates/status.json')['state'] in ('held', 'rolled_back')
    print('Restart recovery restored the original cached runtime and world; hold prevents re-updating.', flush=True)
finally:
    logs = docker('logs', name, check=False)
    if sys.exc_info()[0]:
        print(logs[-24000:])
        print(docker('exec', name, 'cat', '/data/.tmod-control/updates/status.json', check=False))
        print(docker('run', '--rm', '--entrypoint', 'bash', '--volume', volume + ':/data:ro', image,
                     '-c', 'cat /data/.tmod-control/updates/dotnet-install.log /data/tModLoader/Logs/Natives.log 2>/dev/null; '
                           'find /data/.tmod-control/updates/transactions -name compatibility.log -exec tail -60 {} \\;', check=False))
    docker('rm', '--force', name, check=False)
    docker('volume', 'rm', volume, check=False)
