#!/usr/bin/env python3
"""Cold backup and staged restore for a local Linux Docker bind mount."""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sync_directory(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def inspect(container, data):
    info = json.loads(docker('inspect', container))[0]
    mounts = [m for m in info['Mounts'] if m['Destination'] == '/data']
    if len(mounts) != 1 or mounts[0]['Type'] != 'bind':
        raise ValueError('The container must bind-mount the specified host directory at /data.')
    if Path(mounts[0]['Source']).resolve() != data or not mounts[0]['RW']:
        raise ValueError('The /data mount does not match --data or is read-only.')
    if any(m['Destination'].startswith('/data/') for m in info['Mounts']):
        raise ValueError('Nested mounts under /data are not supported.')
    if info['State']['Status'] not in ('running', 'exited', 'created'):
        raise ValueError('Container must be running or stopped, not paused/restarting.')
    return info


def wait_healthy(container, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = json.loads(docker('inspect', container))[0]['State']
        if not state['Running']:
            raise RuntimeError('Server exited during startup; inspect docker logs.')
        if state.get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(2)
    raise RuntimeError('Server did not become healthy before the timeout; inspect docker logs.')


def stop(container, timeout):
    since = datetime.datetime.now(datetime.timezone.utc).isoformat()
    docker('stop', '--time', str(timeout), container)
    state = json.loads(docker('inspect', container))[0]['State']
    output = subprocess.check_output(['docker', 'logs', '--since', since, container],
                                     text=True, stderr=subprocess.STDOUT)
    if state['Running'] or state['ExitCode'] != 0 or 'Graceful shutdown timed out' in output:
        raise RuntimeError('Server did not stop cleanly; no backup or restore will proceed.')


def scan_tree(data):
    for root, dirs, files in os.walk(data, followlinks=False):
        if Path(root) == data:
            dirs[:] = [name for name in dirs if name != '.tmod-control']
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError(f'Links and special files are unsupported: {path}')
            if path.is_mount():
                raise ValueError(f'Nested filesystem mounts are unsupported: {path}')


def validate(bundle):
    metadata = json.loads((bundle / 'manifest.json').read_text())
    archive = bundle / 'data.tar.gz'
    if metadata.get('format') != 1 or digest(archive) != metadata.get('sha256'):
        raise ValueError('Unsupported backup format or archive checksum mismatch.')
    names = set()
    root_directory = False
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] != 'data' or '\\' in member.name
                    or '.tmod-control' in path.parts
                    or not (member.isdir() or member.isfile())
                    or member.name in names or (member.isfile() and member.mode & 0o7000)):
                raise ValueError(f'Unsafe archive entry: {member.name}')
            names.add(member.name)
            if member.name == 'data':
                root_directory = member.isdir()
            if member.isfile():
                with tar.extractfile(member) as stream:
                    while stream.read(1024 * 1024):
                        pass
    if not root_directory:
        raise ValueError('Backup has no data root.')
    return metadata


def create_backup(data, destination, info):
    scan_tree(data)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    final = destination / f'tmod-backup-{stamp}-{uuid.uuid4().hex[:8]}'
    with tempfile.TemporaryDirectory(prefix='.backup-', dir=destination) as temp:
        staging = Path(temp)
        archive = staging / 'data.tar.gz'
        with tarfile.open(archive, 'w:gz', dereference=False) as tar:
            tar.add(data, arcname='data', filter=lambda member: None
                    if '.tmod-control' in PurePosixPath(member.name).parts else member)
        metadata = {'format': 1, 'created': stamp, 'image_id': info['Image'],
                    'source': info.get('Source', str(data)),
                    'image_reference': info['Config']['Image'],
                    'sha256': digest(archive)}
        (staging / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        validate(staging)
        for path in (archive, staging / 'manifest.json'):
            with path.open('r+b') as stream:
                os.fsync(stream.fileno())
        sync_directory(staging)
        staging.rename(final)
        sync_directory(destination)
    print(f'Verified backup: {final}', flush=True)
    return final


def retain(destination, count, current):
    candidates = []
    source = validate(current)['source']
    for path in destination.glob('tmod-backup-*'):
        if path.is_dir() and not path.is_symlink():
            try:
                if validate(path).get('source') != source:
                    continue
            except (ValueError, OSError, tarfile.TarError, KeyError):
                continue
            candidates.append(path)
    candidates.sort(key=lambda p: p.name, reverse=True)
    keep = {current, *candidates[:count]}
    for path in candidates:
        if path not in keep:
            shutil.rmtree(path)
            print(f'Retention removed verified backup: {path}', flush=True)


@contextlib.contextmanager
def lock(data):
    path = data.parent / f'.{data.name}.backup-lock'
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise RuntimeError(f'Backup/restore lock exists: {path}. Check for an active job before removing it.')
    try:
        yield
    finally:
        path.rmdir()


def restore(bundle, data, info, args):
    metadata = validate(bundle)
    if metadata['image_id'] != info['Image']:
        raise ValueError('Backup image differs from the container image. Recreate the container with the recorded image ID before restoring.')
    with tarfile.open(bundle / 'data.tar.gz', 'r:gz') as tar:
        required = sum(member.size for member in tar if member.isfile())
    if required > shutil.disk_usage(data.parent).free:
        raise ValueError('Insufficient free space to stage the restored data.')
    # Extract before downtime. Only regular files/directories passed validation.
    with tempfile.TemporaryDirectory(prefix=f'.{data.name}-restore-', dir=data.parent) as temp:
        stage = Path(temp)
        with tarfile.open(bundle / 'data.tar.gz', 'r:gz') as tar:
            tar.extractall(stage, numeric_owner=True, filter='fully_trusted')
        running = info['State']['Running']
        if running:
            stop(args.container, args.stop_timeout)
        old = data.parent / f'{data.name}.before-restore-{uuid.uuid4().hex}'
        data.rename(old)
        try:
            (stage / 'data').rename(data)
        except BaseException:
            old.rename(data)
            if running:
                docker('start', args.container)
                wait_healthy(args.container, args.health_timeout)
            raise
        sync_directory(data.parent)
        print(f'Original data retained at: {old}', flush=True)
        if running:
            try:
                docker('start', args.container)
                wait_healthy(args.container, args.health_timeout)
            except Exception:
                # Preserve both data sets and leave stopped for explicit recovery.
                docker('stop', '--time', str(args.stop_timeout), args.container)
                raise RuntimeError(f'Restored server failed health validation and was stopped. Original data remains at {old}; restored data remains at {data}.')
        print('Restore complete.' if running else 'Restore complete; previously stopped container remains stopped. Health validation pending start.')


def run_backup(data, destination, info, args):
    running = info['State']['Running']
    try:
        if running:
            stop(args.container, args.stop_timeout)
        result = create_backup(data, destination, info)
    finally:
        if running:
            docker('start', args.container)
            wait_healthy(args.container, args.health_timeout)
    retain(destination, args.keep, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['backup', 'verify', 'restore'])
    parser.add_argument('--container', default='tmodloader')
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--backups', type=Path, default=Path('backups'))
    parser.add_argument('--archive', type=Path, help='Backup bundle directory for verify/restore')
    parser.add_argument('--keep', type=int, default=7)
    parser.add_argument('--stop-timeout', type=int, default=120)
    parser.add_argument('--health-timeout', type=int, default=600)
    parser.add_argument('--confirm', action='store_true', help='Authorize replacing data during restore')
    args = parser.parse_args()
    os.umask(0o077)
    def interrupted(signum, frame):
        raise RuntimeError('Operation interrupted; inspect server state and retained data before retrying.')
    signal.signal(signal.SIGTERM, interrupted)
    if args.command == 'verify':
        if args.archive is None:
            parser.error('--archive is required')
        print(json.dumps(validate(args.archive.resolve()), indent=2))
        return
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Backup/restore requires root on the local Linux Docker host to preserve file ownership. Verify works without root.')
    if min(args.keep, args.stop_timeout, args.health_timeout) < 1:
        parser.error('Retention and timeouts must be positive.')
    if args.command == 'restore' and (args.archive is None or not args.confirm):
        parser.error('Restore requires --archive and --confirm.')
    endpoint = os.environ.get('DOCKER_HOST')
    if not endpoint:
        endpoint = json.loads(docker('context', 'inspect'))[0]['Endpoints']['docker']['Host']
    if not endpoint.startswith('unix://'):
        parser.error('Only a local Docker daemon over a Unix socket is supported.')
    data = args.data.resolve(strict=True)
    destination = args.backups.resolve()
    if len(data.parts) < 3 or data in (Path('/root'), Path('/home')) or not data.is_dir() or data == destination or data in destination.parents or destination in data.parents:
        parser.error('Data and backup directories must be separate, non-nested directories.')
    with lock(data):
        info = inspect(args.container, data)
        if args.command == 'restore':
            restore(args.archive.resolve(), data, info, args)
            return
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        run_backup(data, destination, info, args)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
