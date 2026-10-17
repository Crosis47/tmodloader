"""Bounded config snapshots, staged with profiles and written only during apply."""
import base64
from contextlib import contextmanager
import hashlib
import json

import admin_modconfigs as configs
import admin_settings as settings

STORAGE_LIMIT = 32 * 1024 * 1024
SNAPSHOT_LIMIT = 16 * 1024 * 1024
FILE_LIMIT = 64


def read_json(path, default):
    if not path.exists():
        return default
    with path.open('rb') as stream:
        data = stream.read(STORAGE_LIMIT + 1)
    if len(data) > STORAGE_LIMIT:
        raise ValueError('Profile config storage exceeds 32 MiB. Remove unused snapshots.')
    return json.loads(data)


def capture(names):
    if not isinstance(names, list) or len(names) > FILE_LIMIT or any(not isinstance(name, str) for name in names):
        raise ValueError('Select up to 64 configuration files.')
    if len(set(names)) != len(names):
        raise ValueError('Select each configuration file only once.')
    records, total = [], 0
    for name in names:
        current = configs.read(name)
        configs.validate_content(name, current['content'])
        with configs.path_for(name).open('rb') as stream:
            raw = stream.read(configs.LIMIT + 1)
        if hashlib.sha256(raw).hexdigest() != current['revision']:
            raise ValueError('A configuration changed while saving the profile. Try again.')
        total += len(raw)
        if total > SNAPSHOT_LIMIT:
            raise ValueError('Selected configuration files exceed 16 MiB per profile.')
        records.append({'name': name, 'data': base64.b64encode(raw).decode('ascii'), 'revision': current['revision']})
    return records


def decode(record):
    try:
        raw = base64.b64decode(record['data'], validate=True)
        if len(raw) > configs.LIMIT or hashlib.sha256(raw).hexdigest() != record['revision']:
            raise ValueError('Snapshot checksum mismatch.')
        configs.validate_content(record['name'], raw.decode('utf-8-sig'))
        return raw
    except (KeyError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError('Invalid profile configuration snapshot. Save the profile again.') from error


def pending_path():
    return settings.PENDING.with_name('pending-profile-configs.json')


def pending():
    records = read_json(pending_path(), [])
    if not isinstance(records, list) or len(records) > FILE_LIMIT:
        raise ValueError('Invalid staged profile configurations. Discard the draft and load the profile again.')
    return records


def stage(records):
    result = []
    for record in records:
        decode(record)
        current = configs.read(record['name'])
        result.append({**record, 'disk_revision': current['revision']})
    return result


def stage_draft(records, values):
    path = pending_path()
    previous = path.read_bytes() if path.exists() else None
    try:
        settings.atomic_json(path, records)
        settings.atomic_json(settings.PENDING, values)
    except Exception:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            configs.atomic_bytes(path, previous)
        raise


def check_pending():
    records = pending()
    for record in records:
        decode(record)
        current = configs.read(record['name'])
        if current['revision'] not in (record['disk_revision'], record['revision']):
            raise ValueError('Configuration changed on disk: ' + record['name'] + '. Load the profile again and review before applying.')
    return records


@contextmanager
def applying():
    # The supervisor calls this only after stopping the game. Check the entire
    # batch before writing and roll back earlier files/history if any write fails.
    records = check_pending()
    written = []
    try:
        for record in records:
            current = configs.read(record['name'])
            if current['revision'] == record['revision']:
                continue  # Retry after a failed game start; already restored.
            path = configs.path_for(record['name'])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['disk_revision']:
                raise ValueError('Configuration changed during apply: ' + record['name'])
            history = configs.history_path(record['name'], create=True)
            old_history = history.read_bytes() if history.exists() else None
            configs.write_version(current, decode(record))
            written.append((path, raw, history, old_history, record['revision']))
        yield
    except Exception as error:
        incomplete = []
        for path, raw, history, old_history, restored_revision in reversed(written):
            try:
                if hashlib.sha256(path.read_bytes()).hexdigest() != restored_revision:
                    raise ValueError('File changed again during rollback.')
                configs.atomic_bytes(path, raw)
                if old_history is None:
                    history.unlink(missing_ok=True)
                else:
                    configs.atomic_bytes(history, old_history)
            except (OSError, ValueError):
                incomplete.append(path.name)
        if incomplete:
            raise ValueError('Config restore failed and rollback needs attention for: ' + ', '.join(incomplete)
                             + '. Newer edits were preserved. Inspect these files before applying again.') from error
        raise
