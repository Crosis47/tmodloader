"""Read-only backup inventory and persistent operation status."""
import datetime
import json
import os
from pathlib import Path
import shutil
import sys

from admin_settings import atomic_json, read_json, RUNTIME

DATA = Path(os.environ.get('TMOD_DATA_DIR', '/data'))
DEST = Path('/backups')
STATE = DATA / '.tmod-control' / 'backup-status.json'


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record(state, detail=''):
    previous = read_json(STATE)
    value = {'state': state, 'updated': timestamp(), 'detail': detail,
             'last_success': previous.get('last_success')}
    if state == 'success':
        value['last_success'] = value['updated']
    atomic_json(STATE, value)


def inventory():
    items, warnings = [], []
    usage = shutil.disk_usage(DEST) if DEST.exists() else None
    if not DEST.is_mount():
        warnings.append('No separate /backups mount is available.')
    effective = read_json(RUNTIME / 'admin-effective.json')
    if usage and usage.free < int(effective.get('TMOD_BACKUP_MIN_FREE_MB', os.environ.get('TMOD_BACKUP_MIN_FREE_MB', '1024'))) * 1024 * 1024:
        warnings.append('Backup storage is below the configured free-space reserve.')
    if DEST.exists():
        for path in sorted(DEST.glob('tmod-backup-*'), reverse=True)[:1000]:
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                metadata = read_json(path / 'manifest.json')
                archive = path / 'data.tar.gz'
                items.append({'name': path.name, 'created': metadata.get('created'),
                              'bytes': archive.stat().st_size, 'format': metadata.get('format'),
                              'verification': 'Not rechecked; use Verify to check the archive checksum.'})
            except (OSError, ValueError):
                warnings.append(f'Incomplete or unreadable bundle: {path.name}')
    state = read_json(STATE)
    return {'operation': state, 'archives': items, 'count': len(items),
            'inventory_limit': 1000, 'bytes': sum(item['bytes'] for item in items),
            'free_bytes': usage.free if usage else None, 'total_bytes': usage.total if usage else None,
            'warnings': warnings}


if __name__ == '__main__':
    if sys.argv[1] == 'startup':
        if read_json(STATE).get('state') == 'running':
            record('interrupted', 'Container restarted before backup completion was recorded; verify the latest archive.')
    else:
        record(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
