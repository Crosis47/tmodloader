"""Persist one upgrade notice per container version, independent of browser storage."""
import re
from pathlib import Path

import admin_settings as settings

BASE = Path(__file__).parent


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Invalid container version.')
    return tuple(map(int, value.split('.')))


def highlights():
    current = (BASE / 'VERSION').read_text().strip()
    version(current)
    data = settings.read_json(BASE / 'release-highlights.json')
    if not isinstance(data, dict):
        raise ValueError('Invalid release highlights.')
    rows = data.get('highlights')
    if data.get('version') != current or not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Release highlights do not match the container version.')
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= limit
                                            for key, limit in (('title', 100), ('description', 600))):
            raise ValueError('Invalid release highlights.')
    return {'available': True, 'version': current, 'highlights': rows,
            'url': 'https://github.com/Crosis47/tmodloader/releases/tag/' + current}


def state_path():
    return settings.PENDING.with_name('release-notice.json')


def initialize(existing_install):
    current = highlights()['version']
    previous = settings.read_json(state_path())
    if not isinstance(previous, dict):
        raise ValueError('Invalid release notice state.')
    old = previous.get('version')
    if old == current:
        return
    # The first release with notices recognizes existing saved credentials as
    # an upgrade. Fresh setup records a baseline without showing upgrade news.
    upgraded = version(current) > version(old) if old else existing_install
    settings.atomic_json(state_path(), {'version': current, 'pending': bool(upgraded)})


def status():
    try:
        data = highlights()
        saved = settings.read_json(state_path())
        if not isinstance(saved, dict):
            raise ValueError('Invalid release notice state.')
        return {**data, 'pending': saved.get('version') == data['version'] and saved.get('pending') is True}
    except (OSError, ValueError, TypeError):
        return {'available': False, 'pending': False}


def dismiss(payload):
    current = highlights()['version']
    if payload.get('version') != current:
        raise ValueError('The container version changed. Refresh the dashboard to see its highlights.')
    settings.atomic_json(state_path(), {'version': current, 'pending': False})
    return status()
