"""Bounded, persistent Workshop selections; profiles never contain world settings."""
import hashlib
import json
import uuid

import admin_settings as settings


def catalog():
    rows = settings.read_json(settings.PENDING.with_name('mod-profiles.json'), [])
    if not isinstance(rows, list):
        raise ValueError('Invalid mod profile catalog.')
    return {'profiles': rows, 'catalog_revision': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def change(payload, current):
    state = catalog()
    if payload.get('catalog_revision') != state['catalog_revision']:
        raise ValueError('Profiles changed. Refresh before trying again.')
    rows = state['profiles']
    kind = payload.get('action')
    if kind not in ('save', 'rename', 'delete', 'stage'):
        raise ValueError('Choose a supported profile action.')
    selected = next((row for row in rows if row['id'] == payload.get('id')), None)
    if (kind != 'save' or payload.get('id')) and selected is None:
        raise ValueError('Profile no longer exists. Refresh the list.')
    if kind in ('save', 'stage') and payload.get('revision') != current['revision']:
        raise ValueError('Settings changed. Refresh and review the latest selection.')
    if kind == 'stage':
        if not settings.web_mode():
            raise ValueError('Enable web-managed settings to load a profile.')
        removed = []
        values = settings.clean_mod_selection(settings.validate({'TMOD_MODS': selected['mods']}), removed)
        settings.atomic_json(settings.PENDING, {**current['staged'], **values})
        settings.record_pending_removals(removed)
        return
    if kind == 'delete' or (kind == 'save' and selected):
        if payload.get('confirm') is not True:
            raise ValueError('Confirm deleting or replacing the profile.')
    if kind in ('save', 'rename'):
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError('Use a profile name of 1–64 characters without control characters.')
        name = name.strip()
        if any(row is not selected and row['name'].casefold() == name.casefold() for row in rows):
            raise ValueError('That profile name already exists.')
        if kind == 'save':
            source = payload.get('source')
            if source not in ('running', 'staged'):
                raise ValueError('Choose the running or saved draft selection.')
            mods = settings.validate({'TMOD_MODS': current[source].get('TMOD_MODS', '')})['TMOD_MODS']
            if selected is None:
                selected = {'id': uuid.uuid4().hex}
                rows.append(selected)
            selected['mods'] = mods
        selected['name'] = name
    else:
        rows.remove(selected)
    if len(rows) > 50 or len((json.dumps(rows, indent=2) + '\n').encode()) > 60000:
        raise ValueError('Profile storage is full (50 profiles or 60 KB). Remove an unused profile first.')
    settings.atomic_json(settings.PENDING.with_name('mod-profiles.json'), rows)
