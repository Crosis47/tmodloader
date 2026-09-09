"""Run as root on a Linux Docker host against the built server image."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backup', root / 'backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
image = sys.argv[1]
name = 'tmod-backup-test-' + uuid.uuid4().hex[:12]
with tempfile.TemporaryDirectory(prefix='tmod-backup-integration-') as temp:
    data = Path(temp) / 'data'
    data.mkdir()
    os.chown(data, 1000, 1000)
    bundles = Path(temp) / 'backups'
    bundles.mkdir()
    os.chown(bundles, 1000, 1000)
    try:
        backup.docker('run', '-d', '--name', name, '--mount', f'type=bind,source={data},target=/data',
                      '--mount', f'type=bind,source={bundles},target=/backups',
                      '-e', 'TMOD_MODS=', '-e', 'TMOD_WORLDSIZE=1', '-e', 'TMOD_AUTOSAVE_INTERVAL=0',
                      '-e', 'TMOD_BACKUP_INTERVAL=1', '-e', 'TMOD_BACKUP_KEEP=2', image)
        backup.wait_healthy(name, 600)
        marker = data / 'restore-proof.txt'
        marker.write_text('before backup')
        os.chown(marker, 1000, 1000)
        backup.docker('exec', name, 'tmod-backup', 'backup')
        bundle = next(bundles.glob('tmod-backup-*'))
        archive = '/backups/' + bundle.name
        backup.docker('exec', name, 'tmod-backup', 'verify', '--archive', archive)
        marker.write_text('after backup')
        restore_command = ['docker', 'run', '--rm', '--entrypoint', 'tmod-backup',
                           '--mount', f'type=bind,source={data},target=/data',
                           '--mount', f'type=bind,source={bundles},target=/backups',
                           image, 'restore', '--archive', archive, '--confirm']
        rejected = subprocess.run(restore_command, capture_output=True, text=True)
        assert rejected.returncode != 0 and 'Data is in use' in rejected.stderr, rejected
        backup.docker('stop', '--time', '120', name)
        subprocess.run(restore_command, check=True)
        assert marker.read_text() == 'before backup'
        previous = next((data / '.tmod-control').glob('before-restore-*'))
        assert (previous / marker.name).read_text() == 'after backup'
        worlds = list((data / 'tModLoader/Worlds').glob('*.wld'))
        assert worlds
        assert all(world.stat().st_uid == 1000 for world in worlds)
        assert data.stat().st_uid == 1000
        backup.docker('start', name)
        backup.wait_healthy(name, 600)
        assert json.loads(backup.docker('inspect', name))[0]['State']['Health']['Status'] == 'healthy'
        existing = {p.name for p in bundles.glob('tmod-backup-*')}
        deadline = time.monotonic() + 180
        while not ({p.name for p in bundles.glob('tmod-backup-*')} - existing):
            if time.monotonic() > deadline:
                raise AssertionError('Scheduled backup did not run')
            time.sleep(2)
        # A bundle is published before restart/retention; wait for the complete cycle.
        deadline = time.monotonic() + 120
        while backup.docker('exec', name, 'bash', '-c', 'if test -f /tmp/tmodloader/backup-result; then cat /tmp/tmodloader/backup-result; fi').splitlines()[:2] != ['scheduled', '0']:
            if time.monotonic() > deadline:
                raise AssertionError('Scheduled backup failed')
            time.sleep(2)
        assert len(list(bundles.glob('tmod-backup-*'))) <= 2
        print('Real-server backup, restore, ownership, and health checks passed.')
    finally:
        backup.docker('rm', '-f', name)
