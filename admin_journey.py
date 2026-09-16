"""Server Journey defaults with optional, independently saved world overrides."""
import hashlib
import json

import admin_settings as settings

KEYS = {'TMOD_JOURNEY_' + key for key in settings.JOURNEY}


def permissions(values):
    return settings.validate({key: value for key, value in values.items() if key in KEYS})


def path(name=None):
    if name is None:
        return settings.PENDING.with_name('journey-defaults.json')
    settings.validate({'TMOD_WORLDNAME': name})
    return settings.PENDING.parent / 'journey-worlds' / (hashlib.sha256(name.encode()).hexdigest() + '.json')


def defaults():
    # Before the first migration, preserve the existing global Journey settings.
    fallback = {key: '0' for key in KEYS}
    fallback.update(permissions(settings.effective()))
    fallback.update(permissions(settings.read_json(settings.ACTIVE)))
    return {**fallback, **permissions(settings.read_json(path()))}


def initialize():
    if not path().exists():
        settings.atomic_json(path(), defaults())


def state(name=None):
    base = defaults()
    override = permissions(settings.read_json(path(name))) if name is not None else {}
    data = {'name': name, 'defaults': base, 'override': bool(override),
            'permissions': {**base, **override}}
    data['revision'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def effective(name):
    return state(name)['permissions']


def save(payload):
    name = payload.get('name')
    current = state(name)
    if payload.get('revision') != current['revision']:
        raise ValueError('Journey permissions changed. Close and reopen this dialog before saving.')
    override = payload.get('override')
    if not isinstance(override, bool):
        raise ValueError('Choose server defaults or a world override.')
    values = payload.get('permissions')
    if not isinstance(values, dict) or set(values) != KEYS:
        raise ValueError('Provide all Journey permissions and no other settings.')
    values = settings.validate(values)
    initialize()
    settings.atomic_json(path(name), values if name is None or override else {})
    return state(name)


def remember_applied(values):
    """An explicitly applied playthrough may supply its own Journey snapshot."""
    name = values.get('TMOD_WORLDNAME')
    chosen = permissions(values)
    if name and chosen and any(value != effective(name)[key] for key, value in chosen.items()):
        initialize()
        settings.atomic_json(path(name), {**effective(name), **chosen})
