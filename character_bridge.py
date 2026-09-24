"""Build the small server-only connection tracking mod against the selected game runtime."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import admin_settings as settings
import admin_updates as updates

NAME = 'ContainerCharacters'
SOURCE = Path(__file__).parent / 'server-mod' / NAME


def prepare(runtime=None, data=None):
    from runtime_updates import dotnet
    runtime = runtime or updates.active()
    data = data or settings.DATA
    mods = data / 'tModLoader/Mods'
    mods.mkdir(parents=True, exist_ok=True)
    cache = data / '.tmod-control/character-bridge'
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256((runtime / 'tModLoader.dll').read_bytes())
    for path in sorted(SOURCE.iterdir()):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    signature = digest.hexdigest()
    marker = cache / 'build.json'
    target = mods / (NAME + '.tmod')
    previous = updates.read(marker)
    installed = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    if previous.get('signature') != signature or not installed or previous.get('mod_sha256') != installed:
        print('[ADMIN] Preparing character connection tracking.', flush=True)
        # Isolated save/log paths keep the build from altering game settings or logs.
        with tempfile.TemporaryDirectory(prefix='build-', dir=cache) as work:
            work = Path(work)
            source = work / NAME
            shutil.copytree(SOURCE, source)
            command = [str(dotnet(runtime)), str(runtime / 'tModLoader.dll'), '-server', '-nosteam',
                       '-tmlsavedirectory', str(work / 'save'), '-build', str(source)]
            with (cache / 'build.log').open('w') as log:
                subprocess.run(command, cwd=runtime, stdout=log, stderr=subprocess.STDOUT,
                               env={**os.environ, 'DOTNET_ROLL_FORWARD': 'Disable'}, timeout=120, check=True)
            built = work / 'save/Mods' / target.name
            shutil.copyfile(built, target.with_suffix('.tmp'))
            target.with_suffix('.tmp').replace(target)
        settings.atomic_json(marker, {'signature': signature, 'mod_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    enabled = settings.read_json(mods / 'enabled.json', [])
    if not isinstance(enabled, list):
        raise ValueError('The enabled mods list is invalid.')
    if NAME not in enabled:
        settings.atomic_json(mods / 'enabled.json', [*enabled, NAME])


if __name__ == '__main__':
    try:
        prepare()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # A future unsupported runtime must not prevent the server from starting.
        print('[ADMIN] Character connection tracking unavailable: ' + str(error) +
              '. See /data/.tmod-control/character-bridge/build.log.', flush=True)
        mods = settings.DATA / 'tModLoader/Mods'
        enabled = settings.read_json(mods / 'enabled.json', [])
        if isinstance(enabled, list) and NAME in enabled:
            settings.atomic_json(mods / 'enabled.json', [item for item in enabled if item != NAME])
