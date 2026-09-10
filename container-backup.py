#!/usr/bin/python3
"""Non-root, container-native backup commands. No Docker socket required."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import time
import uuid


def drop_runtime_privileges():
    """Replace a root CLI invocation with this command running as tml."""
    if os.geteuid() != 0:
        return
    os.execv('/usr/bin/setpriv', [
        'setpriv', '--reuid=tml', '--regid=tml', '--init-groups',
        '--no-new-privs', '--', sys.executable, os.path.realpath(__file__),
        *sys.argv[1:],
    ])


if __name__ == '__main__':
    drop_runtime_privileges()

sys.path.insert(0, '/terraria-server')
import backup

DATA = Path('/data')
DEST = Path('/backups')
CONTROL = DATA / '.tmod-control'
RUNTIME = Path(os.environ.get('TMOD_RUNTIME_DIR', '/tmp/tmodloader'))


@contextlib.contextmanager
def exclusive(path):
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Data is in use; stop the server before restoring.')
        yield


def preflight(check_reserve=True):
    if not DEST.is_mount() or os.path.samefile(DEST, DATA):
        raise ValueError('/backups must be a separate writable mount, not container storage.')
    for root, dirs, files in os.walk(DATA, followlinks=False):
        if os.path.samefile(root, DEST):
            raise ValueError('/backups cannot refer to a directory inside /data.')
    with tempfile.TemporaryFile(dir=DEST):
        pass
    reserve = int(os.environ.get('TMOD_BACKUP_MIN_FREE_MB', '1024')) * 1024 * 1024
    if reserve < 0:
        raise ValueError('TMOD_BACKUP_MIN_FREE_MB must be non-negative.')
    if check_reserve and shutil.disk_usage(DEST).free < reserve:
        raise ValueError('Backup storage is below TMOD_BACKUP_MIN_FREE_MB; free space before retrying.')


def identity():
    return Path('/terraria-server/backup-build-id').read_text().strip()


def cold_backup():
    preflight()
    if (RUNTIME / 'server.pid').exists():
        raise RuntimeError('Refusing to archive while the server is running.')
    # Only the supervisor calls this, after reaping a cleanly exited server.
    source = CONTROL / 'dataset-id'
    if not source.exists():
        source.write_text(uuid.uuid4().hex)
    info = {'Image': identity(), 'Config': {'Image': 'container-build-fingerprint'},
            'Source': source.read_text().strip()}
    result = backup.create_backup(DATA, DEST, info)
    return result


def request_backup():
    try:
        preflight()
    except Exception:
        import admin_metrics
        admin_metrics.record('failed', 'Backup mount or free-space preflight failed; server was not stopped')
        raise
    if not (RUNTIME / 'supervisor.pid').exists():
        raise RuntimeError('No running supervisor; use docker compose exec for backup.')
    with exclusive(RUNTIME / 'backup-client.lock'):
        request_id = uuid.uuid4().hex
        response = RUNTIME / 'backup-result'
        response.unlink(missing_ok=True)
        request = RUNTIME / 'backup-request'
        temporary = RUNTIME / 'backup-request.tmp'
        temporary.write_text(request_id)
        temporary.replace(request)
        print('Backup requested; waiting for shutdown, archive verification and restart.', flush=True)
        while True:
            if response.exists():
                result = response.read_text().splitlines()
                if result and result[0] == request_id:
                    print('\n'.join(result[2:]))
                    if result[1] != '0':
                        raise RuntimeError('Backup failed; inspect docker compose logs.')
                    return
            pid = int((RUNTIME / 'supervisor.pid').read_text())
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                raise RuntimeError('Supervisor exited; inspect logs before retrying.')
            time.sleep(1)


def restore(bundle):
    preflight(check_reserve=False)
    CONTROL.mkdir(mode=0o700, exist_ok=True)
    with exclusive(CONTROL / 'server.lock'):
        pending = CONTROL / 'restore-pending'
        if pending.exists():
            raise RuntimeError('An interrupted restore needs manual recovery; see /data/.tmod-control/restore-pending.')
        metadata = backup.validate(bundle)
        if metadata['image_id'] != identity():
            raise ValueError('Backup build fingerprint differs; use the original image to restore.')
        backup.scan_tree(DATA)
        with tarfile.open(bundle / 'data.tar.gz', 'r:gz') as tar:
            required = sum(m.size for m in tar if m.isfile())
        if required > shutil.disk_usage(DATA).free:
            raise ValueError('Insufficient space to stage restored data alongside original data.')
        with tempfile.TemporaryDirectory(prefix='restore-stage-', dir=CONTROL) as temp:
            stage = Path(temp)
            with tarfile.open(bundle / 'data.tar.gz', 'r:gz') as tar:
                tar.extractall(stage, filter='fully_trusted')
            for root, dirs, files in os.walk(stage, topdown=False):
                for name in files:
                    with (Path(root) / name).open('rb') as stream:
                        os.fsync(stream.fileno())
                backup.sync_directory(Path(root))
            old = CONTROL / ('before-restore-' + uuid.uuid4().hex)
            old.mkdir(mode=0o700)
            pending.write_text(f'Original data: {old}\nArchive: {bundle}\n')
            with pending.open('r+b') as stream:
                os.fsync(stream.fileno())
            backup.sync_directory(CONTROL)
            # Mount roots cannot be renamed. Keep originals on the same filesystem
            # and block server startup if interrupted during the per-entry move.
            for item in DATA.iterdir():
                if item.name != '.tmod-control':
                    item.rename(old / item.name)
            backup.sync_directory(old)
            for item in (stage / 'data').iterdir():
                item.rename(DATA / item.name)
            backup.sync_directory(DATA)
            pending.unlink()
            backup.sync_directory(CONTROL)
            print(f'Restore complete. Original data retained at {old}. Start the server and verify health.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['backup', 'verify', 'restore', '_cold', '_retain', '_preflight'])
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if args.command in ('verify', 'restore', '_retain') and args.archive is None:
        parser.error('--archive is required')
    if args.command == 'backup':
        request_backup()
    elif args.command == '_preflight':
        preflight()
    elif args.command == '_cold':
        result = cold_backup()
        (RUNTIME / 'backup-archive').write_text(str(result))
    elif args.command == '_retain':
        backup.retain(DEST, int(os.environ.get('TMOD_BACKUP_KEEP', '7')), args.archive)
    elif args.command == 'verify':
        print(json.dumps(backup.validate(args.archive), indent=2))
    elif args.command == 'restore':
        if not args.confirm:
            parser.error('Restore requires --confirm and a stopped server.')
        restore(args.archive.resolve())


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
