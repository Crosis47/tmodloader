"""Saved world inventory and guarded world-selection drafts."""
import datetime
import os
import shutil

import admin_settings as settings

CREATION_KEYS = {'TMOD_WORLDSIZE', 'TMOD_DIFFICULTY', 'TMOD_WORLDSEED', 'TMOD_WORLDEVIL'}


def directory():
    path = settings.DATA / 'tModLoader/Worlds'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('World directory must not be a symbolic link.')
    return path


def world_path(name):
    name = settings.validate({'TMOD_WORLDNAME': name})['TMOD_WORLDNAME']
    path = directory() / (name + '.wld')
    if path.is_symlink() or path.with_suffix('.twld').is_symlink():
        raise ValueError('Linked world files cannot be managed here.')
    return path


def check(kind, name):
    path = world_path(name)
    if kind == 'create':
        # Preserve existing worlds and sidecars, including incomplete creation.
        if any(path.with_suffix(suffix).exists() for suffix in ('.wld', '.twld', '.wld.bak', '.twld.bak')):
            raise ValueError('That world name already has saved files. Choose an unused name or switch to the existing world.')
    elif kind == 'switch':
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('The selected world is missing or empty. Refresh the world list.')
    else:
        raise ValueError('Choose Create or Switch.')


def inventory(running):
    root = directory()
    custom = os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1')
    current = None if custom else running.get('TMOD_WORLDNAME')
    rows, warnings = [], []
    paths = sorted(root.glob('*.wld'), key=lambda p: p.name.casefold()) if root.exists() else []
    for path in paths[:1000]:
        try:
            world_path(path.stem)
            if not path.is_file():
                continue
            info = path.stat()
            sidecar = path.with_suffix('.twld')
            sidecar_present = sidecar.is_file()
            rows.append({'name': path.stem, 'filename': path.name, 'bytes': info.st_size,
                         'mod_bytes': sidecar.stat().st_size if sidecar_present else 0,
                         'modified': datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat(),
                         'has_mod_data': sidecar_present, 'selected': path.stem == current,
                         'can_select': info.st_size > 0})
        except (OSError, ValueError) as error:
            warnings.append(f'{path.name}: {error}')
    if len(paths) > 1000:
        warnings.append('Showing the first 1000 worlds.')
    if current and not any(row['selected'] for row in rows):
        warnings.append('The configured world has no saved file yet. It may still be generating.')
    return {'worlds': rows, 'configured': current, 'editable': settings.web_mode() and not custom,
            'warnings': warnings, 'free_bytes': shutil.disk_usage(settings.DATA).free,
            'detail': 'Custom configuration controls the active world. This list shows the standard saved-world directory only.' if custom else
                      'Size and modification time describe saved files. Generation settings do not change existing worlds.'}


def stage(payload, current):
    kind, name = payload.get('action'), payload.get('name')
    check(kind, name)
    values = {'TMOD_WORLDNAME': name}
    if kind == 'create':
        creation = payload.get('creation', {})
        if not isinstance(creation, dict) or set(creation) != CREATION_KEYS:
            raise ValueError('Provide world size, difficulty, evil and seed for creation.')
        values.update(settings.validate(creation))
        if not name.strip() or len(name.encode('utf-16-le')) > 52 or len(values['TMOD_WORLDSEED'].encode('utf-16-le')) > 78:
            raise ValueError('New worlds require a nonblank name up to 26 characters and a seed up to 39 characters.')
    settings.atomic_json(settings.PENDING.with_name('pending-world.json'), {'action': kind, 'name': name})
    settings.atomic_json(settings.PENDING, {**current['staged'], **values})


def validate_pending():
    if not settings.PENDING.exists():
        return
    intent = settings.read_json(settings.PENDING.with_name('pending-world.json'))
    values = settings.read_json(settings.PENDING)
    if intent and intent.get('name') == values.get('TMOD_WORLDNAME'):
        check(intent.get('action'), intent['name'])
