"""Saved world, Journey and mod selections."""
import hashlib
import json
import uuid

import admin_settings as settings
import admin_worlds as worlds
import os

KEYS = worlds.CREATION_KEYS | {"TMOD_WORLDNAME", "TMOD_MODS"} | {"TMOD_JOURNEY_" + key for key in settings.JOURNEY}

def selection(values):
    return settings.validate({key: value for key, value in values.items() if key in KEYS})

def editable():
    return settings.web_mode() and os.environ.get("TMOD_USECONFIGFILE", "No").lower() not in ("yes", "true", "1")


def catalog():
    rows = settings.read_json(settings.PENDING.with_name('playthroughs.json'), [])
    if not isinstance(rows, list):
        raise ValueError('Invalid mod playthrough catalog.')
    return {'playthroughs': rows, 'catalog_revision': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def change(payload, current):
    state = catalog()
    if payload.get('catalog_revision') != state['catalog_revision']:
        raise ValueError('Playthroughs changed. Refresh before trying again.')
    rows = state['playthroughs']
    kind = payload.get('action')
    if kind not in ('save', 'rename', 'delete', 'stage'):
        raise ValueError('Choose a supported playthrough action.')
    selected = next((row for row in rows if row['id'] == payload.get('id')), None)
    if (kind != 'save' or payload.get('id')) and selected is None:
        raise ValueError('Playthrough no longer exists. Refresh the list.')
    if kind in ('save', 'stage') and payload.get('revision') != current['revision']:
        raise ValueError('Settings changed. Refresh and review the latest selection.')
    if kind == 'stage':
        if not editable():
            raise ValueError('Enable web-managed settings to load a playthrough.')
        removed = []
        values = settings.clean_mod_selection(selection(selected['settings']), removed)
        name = values.get('TMOD_WORLDNAME')
        worlds.check('switch', name)
        settings.atomic_json(settings.PENDING.with_name('pending-world.json'), {'action': 'switch', 'name': name})
        settings.atomic_json(settings.PENDING, {**current['staged'], **values})
        settings.record_pending_removals(removed)
        return
    if kind == 'delete' or (kind == 'save' and selected):
        if payload.get('confirm') is not True:
            raise ValueError('Confirm deleting or replacing the playthrough.')
    if kind in ('save', 'rename'):
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError('Use a playthrough name of 1–64 characters without control characters.')
        name = name.strip()
        if any(row is not selected and row['name'].casefold() == name.casefold() for row in rows):
            raise ValueError('That playthrough name already exists.')
        if kind == 'save':
            source = payload.get('source')
            if source not in ('running', 'staged'):
                raise ValueError('Choose the running or saved draft selection.')
            values = selection(current[source])
            values.update(settings.validate({'TMOD_WORLDNAME': payload.get('world', values.get('TMOD_WORLDNAME'))}))
            worlds.check('switch', values['TMOD_WORLDNAME'])
            if selected is None:
                selected = {'id': uuid.uuid4().hex}
                rows.append(selected)
            selected['settings'] = values
        selected['name'] = name
    else:
        rows.remove(selected)
    if len(rows) > 50 or len((json.dumps(rows, indent=2) + '\n').encode()) > 60000:
        raise ValueError('Playthrough storage is full (50 playthroughs or 60 KB). Remove an unused playthrough first.')
    settings.atomic_json(settings.PENDING.with_name('playthroughs.json'), rows)
