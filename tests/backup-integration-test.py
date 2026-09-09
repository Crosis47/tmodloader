"""Run as root on a Linux Docker host against the built server image."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
    try:
        backup.docker('run', '-d', '--name', name, '--mount', f'type=bind,source={data},target=/data',
                      '-e', 'TMOD_MODS=', '-e', 'TMOD_WORLDSIZE=1', '-e', 'TMOD_AUTOSAVE_INTERVAL=0', image)
        backup.wait_healthy(name, 600)
        marker = data / 'restore-proof.txt'
        marker.write_text('before backup')
        base = [sys.executable, str(root / 'backup.py')]
        common = ['--container', name, '--data', str(data), '--backups', str(bundles)]
        subprocess.run(base + ['backup', *common], check=True)
        bundle = next(bundles.glob('tmod-backup-*'))
        marker.write_text('after backup')
        subprocess.run(base + ['restore', *common, '--archive', str(bundle), '--confirm'], check=True)
        assert marker.read_text() == 'before backup'
        previous = next(Path(temp).glob('data.before-restore-*'))
        assert (previous / marker.name).read_text() == 'after backup'
        assert list((data / 'tModLoader/Worlds').glob('*.wld'))
        assert json.loads(backup.docker('inspect', name))[0]['State']['Health']['Status'] == 'healthy'
        print('Real-server backup, restore, ownership, and health checks passed.')
    finally:
        backup.docker('rm', '-f', name)
