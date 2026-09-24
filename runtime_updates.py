"""Cold-start runtime/mod updates with copied-world validation and recovery checkpoints.

Only the supervisor calls boot/prepare, while holding the server data lock.
The dashboard only discovers releases and queues recovery for the next restart.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid
import zipfile

import admin_settings as settings
import admin_updates as updates

GAME = ('steamMods', 'tModLoader/Mods', 'tModLoader/Worlds', 'tModLoader/ModConfigs', 'tModLoader/banlist.txt',
        'admin/settings.json')
MODS = GAME[:2]


def report(state, detail, **extra):
    settings.atomic_json(updates.ROOT / 'status.json', {'state': state, 'detail': detail,
                                                     'updated': updates.stamp(), **extra})
    print('[UPDATE] ' + detail, flush=True)


def safe_tree(path):
    """Reject links/devices before copying data or recursively removing our staging files."""
    if path.is_symlink():
        raise ValueError('Linked paths cannot participate in an update: ' + str(path))
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        raise ValueError('Unsupported file type: ' + str(path))
    size = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            child = Path(root) / name
            if child.is_symlink() or not (child.is_dir() or child.is_file()):
                raise ValueError('Unsupported linked or special file: ' + str(child))
            if child.is_file():
                size += child.stat().st_size
    return size


def copy(source, target):
    safe_tree(source)
    if source.is_dir():
        shutil.copytree(source, target)
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def remove(path):
    safe_tree(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def transaction(identity):
    if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
        raise ValueError('Invalid update recovery record.')
    return updates.ROOT / 'transactions' / identity


def snapshot():
    for name in GAME:
        if any(path.is_symlink() for path in (settings.DATA / name).parents):
            raise ValueError('Linked game-data directories cannot participate in an update.')
    size = sum(safe_tree(settings.DATA / name) for name in GAME)
    reserve = int(os.environ.get('TMOD_UPDATE_MIN_FREE_MB', '1024')) * 1024 * 1024
    if reserve < 0 or shutil.disk_usage(settings.DATA).free < size * 3 + reserve:
        raise ValueError('Insufficient free data storage for update staging and recovery copies.')
    identity = uuid.uuid4().hex
    directory = transaction(identity)
    directory.mkdir(parents=True, mode=0o700)
    try:
        for name in GAME:
            copy(settings.DATA / name, directory / 'before' / name)
        settings.atomic_json(directory / 'manifest.json', {'active': updates.read(updates.ROOT / 'active.json'),
                                                         'runtime': updates.runtime(), 'created': updates.stamp()})
    except Exception:
        remove(directory)
        raise
    return identity, directory


def delete_checkpoint(identity):
    if any((updates.ROOT / name).exists() for name in ('journal.json', 'rollback-request.json', 'recovery-cleanup.json')):
        raise ValueError('Finish or cancel pending recovery before deleting its checkpoint.')
    if updates.read(updates.ROOT / 'checkpoint.json').get('id') != identity:
        raise ValueError('The recovery checkpoint changed. Refresh and review it again.')
    directory = transaction(identity)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('Linked checkpoint directories cannot be deleted.')
    if not directory.resolve().is_relative_to(updates.ROOT.resolve() / 'transactions'):
        raise ValueError('Invalid checkpoint location.')
    safe_tree(directory)
    remove(directory)
    (updates.ROOT / 'checkpoint.json').unlink(missing_ok=True)


def restore(identity):
    directory = transaction(identity)
    manifest = updates.read(directory / 'manifest.json')
    if 'active' not in manifest:
        raise ValueError('Update checkpoint is incomplete; recovery requires manual inspection.')
    # The journal remains until ALL paths and the runtime selection are restored.
    # An interrupted restore repeats from the untouched checkpoint on the next boot.
    for name in GAME:
        source, destination = directory / 'before' / name, settings.DATA / name
        remove(destination)
        copy(source, destination)
    settings.atomic_json(updates.ROOT / 'active.json', manifest['active'])


def mark_recovery_cleanup(*identities):
    pending = updates.read(updates.ROOT / 'recovery-cleanup.json').get('checkpoints', [])
    settings.atomic_json(updates.ROOT / 'recovery-cleanup.json',
                         {'checkpoints': list(dict.fromkeys([*pending, *identities]))})


def finish_recovery():
    marker = updates.ROOT / 'recovery-cleanup.json'
    if not marker.exists():
        return
    if (updates.ROOT / 'journal.json').exists() or (updates.ROOT / 'rollback-request.json').exists():
        raise ValueError('Recovery is still pending; checkpoint cleanup deferred.')
    subprocess.run(['healthcheck'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identities = updates.read(marker).get('checkpoints', [])
    paths = [transaction(identity) for identity in identities]
    for path in paths:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Linked checkpoint directories cannot be deleted.')
        safe_tree(path)
    for path in paths:
        remove(path)
    if updates.read(updates.ROOT / 'checkpoint.json').get('id') in identities:
        (updates.ROOT / 'checkpoint.json').unlink(missing_ok=True)
    marker.unlink()
    report('rolled_back', 'Recovery complete. Game health verified; recovery checkpoints deleted. Updates remain paused.')


def boot(retry=False):
    updates.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(p.is_symlink() for p in (updates.ROOT, updates.ROOT.parent, settings.DATA)):
        raise ValueError('Update storage cannot use linked directories.')
    journal = updates.read(updates.ROOT / 'journal.json')
    if retry and not journal and not (updates.ROOT / 'rollback-request.json').exists() and not (updates.ROOT / 'recovery-cleanup.json').exists():
        (updates.ROOT / 'hold.json').unlink(missing_ok=True)
    if journal:
        report('recovering', 'Recovering an interrupted runtime/mod switch.')
        restore(journal['checkpoint'])
        mark_recovery_cleanup(journal['checkpoint'])
        settings.atomic_json(updates.ROOT / 'hold.json', {'version': updates.runtime()['tmodloader_version']})
        (updates.ROOT / 'journal.json').unlink()
        report('blocked', 'Interrupted update recovered; previous runtime and data restored.')
    if (updates.ROOT / 'rollback-request.json').exists():
        old = updates.read(updates.ROOT / 'checkpoint.json')['id']
        manifest = updates.read(transaction(old) / 'manifest.json')
        new, _ = snapshot()
        settings.atomic_json(updates.ROOT / 'journal.json', {'checkpoint': new})
        restore(old)
        mark_recovery_cleanup(old, new)
        # Hold the restored release, otherwise the next startup could reapply it.
        settings.atomic_json(updates.ROOT / 'hold.json', {'version': manifest['runtime']['tmodloader_version']})
        for name in ('pending.json', 'pending-world.json', 'pending-removed.json', 'pending-password.json'):
            (settings.DATA / 'admin' / name).unlink(missing_ok=True)
        settings.atomic_json(updates.ROOT / 'checkpoint.json', {'id': new})
        (updates.ROOT / 'rollback-request.json').unlink()
        (updates.ROOT / 'journal.json').unlink()
        report('rolled_back', 'Previous runtime, mods, worlds and saved settings restored; automatic updates held.')
    route_logs(updates.active(), settings.DATA / 'tModLoader/Logs')
    report('initializing', 'Preparing startup; waiting for configuration and admin setup.')


def route_logs(directory, logs):
    link = directory / 'tModLoader-Logs'
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise ValueError('Runtime log path is not the expected managed link.')
    logs.mkdir(parents=True, exist_ok=True)
    link.symlink_to(logs, target_is_directory=True)


def extract(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        total = 0
        for member in bundle.infolist():
            name = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            total += member.file_size
            if (name.is_absolute() or '..' in name.parts or '\\' in member.filename or ':' in member.filename
                    or stat.S_ISLNK(mode) or total > 2 * 1024 ** 3):
                raise ValueError('Unsafe or oversized runtime archive.')
        bundle.extractall(destination)
    for script in destination.rglob('*.sh'):
        script.chmod(0o755)
    for required in ('tModLoader.dll', 'tModLoader.runtimeconfig.json', 'LaunchUtils/ScriptCaller.sh'):
        if not (destination / required).is_file():
            raise ValueError('Incomplete runtime archive: ' + required)


def download(candidate):
    tag = candidate['version']
    updates.version(tag)
    root = updates.ROOT / 'releases' / tag
    if (root / 'installed.json').exists():
        saved = updates.read(root / 'installed.json')
        if digest(root / 'tModLoader.dll') == saved.get('tmodloader_sha256'):
            return root, saved
        raise ValueError('Cached runtime checksum changed. Inspect the runtime cache.')
    temporary = updates.ROOT / ('download-' + uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    try:
        archive = temporary / 'release.zip'
        request = urllib.request.Request(candidate['download'], headers={'User-Agent': 'tmodloader-container-updates'})
        deadline = time.monotonic() + 300
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response, archive.open('wb') as output:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 512 * 1024 ** 2 or time.monotonic() > deadline:
                            raise ValueError('Runtime download exceeds its size or time limit.')
                        output.write(chunk)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 2 or time.monotonic() >= deadline:
                    raise
                time.sleep(2 * (attempt + 1))
        expected = candidate.get('digest')
        if expected and expected != 'sha256:' + digest(archive):
            raise ValueError('Runtime download checksum does not match GitHub.')
        if candidate.get('size') and size != candidate['size']:
            raise ValueError('Runtime download size does not match GitHub.')
        package = temporary / 'package'
        extract(archive, package)
        # Keep installer scratch space on /data; a small /tmp tmpfs cannot hold .NET.
        install_log = updates.ROOT / 'dotnet-install.log'
        with install_log.open('w') as output:
            subprocess.run(['bash', '-c', 'set -Eeo pipefail; cd LaunchUtils; . ./BashUtils.sh; '
                            'LogFile=/tmp/tmod-update-dotnet.log; . ./DotNetVersion.sh; run_script ./InstallDotNet.sh'],
                           cwd=package, env={**os.environ, 'TMPDIR': str(temporary)},
                           check=True, timeout=360, stdout=output, stderr=subprocess.STDOUT)
        executable = dotnet(package)
        subprocess.run([str(executable), '--info'], check=True, timeout=30, stdout=subprocess.DEVNULL)
        saved = {'tmodloader_version': tag, 'tmodloader_sha256': digest(package / 'tModLoader.dll')}
        settings.atomic_json(package / 'installed.json', saved)
        root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(package, root)
        (root / 'tModLoader-Logs').symlink_to(settings.DATA / 'tModLoader/Logs', target_is_directory=True)
        return root, saved
    finally:
        remove(temporary)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dotnet(directory):
    for name in ('dotnet', 'dotnet_arm64'):
        executable = directory / name / 'dotnet'
        if executable.is_file():
            return executable
    raise ValueError('The runtime does not contain a native .NET executable.')


def mod_names(data):
    values = updates.read(data / 'tModLoader/Mods/enabled.json')
    if values == {}:
        return set()
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ValueError('Cannot inspect enabled mod names.')
    return set(values)


def mod_fingerprint(data):
    value = hashlib.sha256()
    for name in MODS:
        root = data / name
        for path in sorted(root.rglob('*')):
            if path.is_file() and (path.suffix == '.tmod' or path.name == 'enabled.json'):
                value.update(str(path.relative_to(data)).encode())
                value.update(digest(path).encode())
    return value.hexdigest()


def probe(directory, data, config, log):
    logs = data / 'tModLoader/Logs'
    route_logs(directory, logs)
    try:
        return probe_process(directory, data, config, log)
    finally:
        if (logs / 'server.log').exists():
            shutil.copy2(logs / 'server.log', log.with_name('compatibility-server.log'))
        route_logs(directory, settings.DATA / 'tModLoader/Logs')


def probe_process(directory, data, config, log):
    """Ask the target tModLoader itself to resolve dependencies and load copied data."""
    if 'ContainerCharacters' in mod_names(data):
        from character_bridge import prepare
        prepare(runtime=directory, data=data)
    text = config.read_text()
    # Custom config may point outside /data or run an unexpected world; block it upstream.
    text = text.replace(str(settings.DATA) + '/', str(data) + '/')
    lines = [line for line in text.splitlines() if line.partition('=')[0].strip().lower()
             not in ('port', 'ip', 'upnp', 'language', 'password', 'maxplayers')]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    lines += [f'port={port}', 'ip=127.0.0.1', 'upnp=0', 'language=en-US', 'maxplayers=1',
              'password=' + uuid.uuid4().hex]
    trial_config = data / 'probe-config.txt'
    trial_config.write_text('\n'.join(lines) + '\n')
    trial_config.chmod(0o600)
    logs = data / 'tModLoader/Logs'
    logs.mkdir(parents=True, exist_ok=True)
    command = ['python3', str(updates.BASE / 'create_world.py'), str(trial_config), str(dotnet(directory)),
               str(directory / 'tModLoader.dll'), '-server', '-nosteam', '-tmlsavedirectory', str(data / 'tModLoader'),
               '-steamworkshopfolder', str(data / 'steamMods/steamapps/workshop'), '-config', str(trial_config)]
    required = mod_names(data)
    environment = {**os.environ, 'DOTNET_ROLL_FORWARD': 'Disable'}
    # No control-pipe or admin credentials should reach the test process.
    for key in list(environment):
        if key.startswith('TMOD_'):
            del environment[key]
    with log.open('w') as output:
        child = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.PIPE,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True, text=True)
        try:
            deadline = time.monotonic() + int(os.environ.get('TMOD_UPDATE_TEST_TIMEOUT', '600'))
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise ValueError('Candidate exited before reaching readiness; inspect the compatibility log.')
                server_log = logs / 'server.log'
                content = ''
                if server_log.exists():
                    with server_log.open('rb') as stream:
                        stream.seek(max(0, server_log.stat().st_size - 8 * 1024 * 1024))
                        content = stream.read(8 * 1024 * 1024).decode('utf-8', errors='replace')
                if 'Server started' in content and 'Mod Load Completed' in content:
                    loaded = set(re.findall(r'Finalizing Content: ([\w.-]+) \(', content))
                    missing = required - loaded
                    if missing:
                        raise ValueError('Candidate did not load enabled mods: ' + ', '.join(sorted(missing)))
                    child.stdin.write('exit\n')
                    child.stdin.flush()
                    if child.wait(timeout=90) != 0:
                        raise ValueError('Candidate failed while saving/exiting its copied world.')
                    return
                time.sleep(1)
            raise ValueError('Compatibility test timed out; the current installation is retained.')
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


def install_initial():
    """Install once, independently of the subsequent automatic-update policy."""
    if updates.runtime().get('tmodloader_version'):
        updates.active()  # Never replace a missing selected runtime silently.
        return False
    report('checking', 'First startup: selecting the initial tModLoader release.')
    pin = os.environ.get('TMOD_UPDATE_VERSION', '')
    if pin:
        target = updates.pinned_release(pin)
    else:
        checked = updates.check()
        if checked.get('error'):
            raise ValueError(checked['error'])
        target = checked['latest']
    report('downloading', 'Installing tModLoader ' + target['version'] + ' and its .NET runtime.',
           target=target['version'])
    _, metadata = download(target)
    settings.atomic_json(updates.ROOT / 'active.json', metadata)
    report('initializing', 'Initial runtime installed; preparing the server.', installed=target['version'])
    return True


def prepare(config):
    auto = os.environ.get('TMOD_AUTO_UPDATE', '1')
    if auto not in ('0', '1'):
        raise ValueError('TMOD_AUTO_UPDATE must be 0 or 1.')
    initial = install_initial()
    if updates.read(updates.ROOT / 'hold.json').get('version'):
        report('held', 'Recovery hold active; preserving the restored runtime and mods. Use Restart game and apply updates from the dashboard when ready.')
        return
    if auto == '0':
        report('staging', 'Automatic runtime updates disabled; preparing the configured Workshop selection.')
        subprocess.run(['bash', str(updates.BASE / 'manage-mods.sh')], check=True)
        report('disabled', 'Automatic runtime updates disabled; using the selected runtime.')
        return
    if os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1'):
        report('blocked', 'Automatic updates require generated configuration; custom configuration is retained.')
        return
    identity = None
    try:
        current = updates.runtime()
        selected, metadata = updates.active(), updates.read(updates.ROOT / 'active.json')
        if initial:
            target = {'version': current['tmodloader_version']}
        else:
            report('checking', 'Checking the selected tModLoader release channel.')
            cached = updates.check()
            if cached.get('error'):
                raise ValueError(cached['error'])
            target = cached['latest']
        pin = os.environ.get('TMOD_UPDATE_VERSION', '')
        if pin:
            updates.version(pin)
            if updates.version(pin) < updates.version(current['tmodloader_version']):
                raise ValueError('Automatic downgrades are blocked. Restore a matching recovery checkpoint instead.')
            target = updates.pinned_release(pin) if pin != current['tmodloader_version'] else {'version': pin}
        if updates.version(target['version']) > updates.version(current['tmodloader_version']):
            report('downloading', 'Downloading tModLoader ' + target['version'] + '.', target=target['version'])
            selected, metadata = download(target)
        report('staging', 'Copying worlds and mods before checking Workshop updates.')
        identity, directory = snapshot()
        data = directory / 'trial'
        data.mkdir()
        for name in GAME:
            copy(directory / 'before' / name, data / name)
        # Stage downloader changes only in the trial tree. Native loader validation
        # determines whether the available .tmod builds and dependencies can load.
        environment = {**os.environ, 'TMOD_DATA_DIR': str(data), 'TMOD_RUNTIME_DIR': str(directory / 'control'),
                       'TMOD_MOD_OFFLINE_POLICY': 'strict'}
        with (directory / 'workshop.log').open('w') as output:
            subprocess.run(['bash', str(updates.BASE / 'manage-mods.sh')], env=environment,
                           check=True, timeout=600, stdout=output, stderr=subprocess.STDOUT)
        changed = selected != updates.active() or mod_fingerprint(data) != mod_fingerprint(settings.DATA)
        if not changed:
            report('current', 'Installed runtime and mods are unchanged.', installed=current['tmodloader_version'])
            remove(directory)
            return
        report('testing', 'Testing the candidate runtime and enabled mods against a copied world.',
               target=metadata.get('tmodloader_version', current['tmodloader_version']), checkpoint=identity)
        probe(selected, data, config, directory / 'compatibility.log')
        settings.atomic_json(updates.ROOT / 'journal.json', {'checkpoint': identity})
        for name in MODS:
            remove(settings.DATA / name)
            copy(data / name, settings.DATA / name)
        settings.atomic_json(updates.ROOT / 'active.json', metadata)
        settings.atomic_json(updates.ROOT / 'checkpoint.json', {'id': identity})
        remove(data)
        report('awaiting_start', 'Compatibility test passed. Waiting for the live server to become healthy; recovery checkpoint retained.',
               installed=updates.runtime()['tmodloader_version'], checkpoint=identity)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        journal = updates.read(updates.ROOT / 'journal.json')
        if journal:
            restore(journal['checkpoint'])
            (updates.ROOT / 'journal.json').unlink()
        report('blocked', str(error)[:500], checkpoint=identity)
        if identity and updates.read(updates.ROOT / 'checkpoint.json').get('id') != identity:
            # Failed trials are diagnostics, not recovery checkpoints. Do not retain
            # two full game copies on every restart of a blocked update.
            for name in ('before', 'trial'):
                remove(transaction(identity) / name)
        if initial:
            raise RuntimeError('Initial server validation failed; inspect diagnostics and retry.') from error
        # No in-place Workshop refresh here: fallback must retain its working mods.
        if (os.environ.get('TMOD_MODS') or os.environ.get('TMOD_ENABLEDMODS')) and not any(
                (settings.DATA / 'tModLoader/Worlds').glob('*.wld')):
            raise RuntimeError('First startup has no existing world to fall back to; refusing to create a world without the requested mods.') from error


if __name__ == '__main__':
    if sys.argv[1] in ('boot', 'restart-boot'):
        boot(retry=sys.argv[1] == 'restart-boot')
    elif sys.argv[1] == 'prepare':
        try:
            prepare(Path(sys.argv[2]))
        except Exception as error:
            # Keep dashboard recovery controls available after any startup failure.
            report('blocked', str(error)[:500], checkpoint=updates.read(updates.ROOT / 'status.json').get('checkpoint'))
            raise
    elif sys.argv[1] == 'launcher':
        route_logs(updates.active(), settings.DATA / 'tModLoader/Logs')
        print(updates.active() / 'LaunchUtils/ScriptCaller.sh')
    elif sys.argv[1] == 'needs-confirmation':
        sys.exit(0 if updates.read(updates.ROOT / 'status.json').get('state') == 'awaiting_start' else 1)
    elif sys.argv[1] == 'confirm':
        (updates.ROOT / 'journal.json').unlink(missing_ok=True)
        report('updated', 'Runtime and mod update passed compatibility and live-server health checks.',
               installed=updates.runtime()['tmodloader_version'], checkpoint=updates.read(updates.ROOT / 'checkpoint.json').get('id'))
    elif sys.argv[1] == 'failed-start':
        boot()
        report('rolled_back', 'Updated server failed readiness. Previous runtime, mods and world checkpoint restored; updates held.')
    elif sys.argv[1] == 'finish-recovery':
        finish_recovery()
