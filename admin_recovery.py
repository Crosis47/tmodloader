"""Recovery status and archive selection shared by the API and restore helper."""
import re
from pathlib import Path

import admin_metrics
import admin_settings as settings


def archive_path(name):
    if not isinstance(name, str) or not re.fullmatch(r'tmod-backup-[A-Za-z0-9-]+', name):
        raise ValueError('Invalid archive name.')
    path = admin_metrics.DEST / name
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Archive not found.')
    for filename in ('manifest.json', 'data.tar.gz'):
        item = path / filename
        if item.is_symlink() or not item.is_file():
            raise ValueError('Archive contains missing or linked files.')
    return path


def status():
    control = settings.DATA / '.tmod-control'
    return {'operation': settings.read_json(control / 'recovery-status.json'),
            'interrupted': (control / 'restore-pending').exists(),
            'originals': sorted(p.name for p in control.glob('before-restore-*')
                                if p.is_dir() and not p.is_symlink()),
            'guidance': 'Original data is retained under /data/.tmod-control. If a restore was interrupted while replacing files, keep the game stopped and recover using restore-pending and the retained original directory.'}


def record(value):
    settings.atomic_json(settings.DATA / '.tmod-control/recovery-status.json', value)
