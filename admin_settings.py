"""Allowlisted, persistent web-managed settings. Secrets are never serialized."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

DATA = Path(os.environ.get('TMOD_DATA_DIR', '/data'))
RUNTIME = Path(os.environ.get('TMOD_RUNTIME_DIR', '/tmp/tmodloader'))
DIRECTORY = DATA / 'admin'
ACTIVE = DIRECTORY / 'settings.json'
PENDING = DIRECTORY / 'pending.json'

RANGES = {
    'TMOD_MAXPLAYERS': (1, 255), 'TMOD_WORLDSIZE': (1, 3),
    'TMOD_DIFFICULTY': (0, 3), 'TMOD_SECURE': (0, 1), 'TMOD_NPCSTREAM': (0, 1000),
    'TMOD_UPNP': (0, 1), 'TMOD_PRIORITY': (0, 5),
    'TMOD_AUTOSAVE_INTERVAL': (0, 9999999), 'TMOD_BACKUP_INTERVAL': (0, 9999999),
    'TMOD_BACKUP_KEEP': (1, 999999), 'TMOD_BACKUP_MIN_FREE_MB': (0, 999999999),
    'TMOD_SHUTDOWN_TIMEOUT': (1, 3600), 'TMOD_CRASH_LOG_LINES': (0, 100000),
    'TMOD_DOWNLOAD_RETRIES': (1, 20), 'TMOD_DOWNLOAD_RETRY_DELAY': (0, 600),
    'TMOD_COLLECTION_MAX_ITEMS': (1, 1000),
}
JOURNEY = ('SETFROZEN SETDAWN SETNOON SETDUSK SETMIDNIGHT GODMODE WIND_STRENGTH '
           'RAIN_STRENGTH TIME_SPEED RAIN_FROZEN WIND_FROZEN PLACEMENT_RANGE '
           'SET_DIFFICULTY BIOME_SPREAD SPAWN_RATE').split()
RANGES.update({'TMOD_JOURNEY_' + key: (0, 2) for key in JOURNEY})
CHOICES = {'TMOD_LOG_LEVEL': ['quiet', 'normal', 'debug'],
           'TMOD_WORLDEVIL': ['random', 'corruption', 'crimson'],
           'TMOD_MOD_OFFLINE_POLICY': ['use-cache', 'strict']}
TEXT = ['TMOD_MOTD', 'TMOD_WORLDNAME', 'TMOD_WORLDSEED', 'TMOD_LANGUAGE',
        'TMOD_SHUTDOWN_MESSAGE', 'TMOD_MODS']
KEYS = set(RANGES) | set(CHOICES) | set(TEXT)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.admin-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    if path.stat().st_size > 65536:
        raise ValueError('Settings file exceeds 64 KiB.')
    return json.loads(path.read_text())


def validate(values):
    if not isinstance(values, dict) or set(values) - KEYS:
        raise ValueError('Unknown settings; networking, paths, and secrets remain Compose-managed.')
    output = {}
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > (16000 if key == 'TMOD_MODS' else 1000):
            raise ValueError(f'{key}: value is too long or is not text.')
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f'{key}: control characters are not allowed.')
        if key in RANGES:
            minimum, maximum = RANGES[key]
            if not re.fullmatch(r'[0-9]{1,9}', value) or not minimum <= int(value) <= maximum:
                raise ValueError(f'{key}: expected {minimum} through {maximum}.')
            value = str(int(value))
        if key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f'{key}: select a supported value.')
        if key == 'TMOD_WORLDNAME' and (not value or value in ('.', '..') or '/' in value or '\\' in value):
            raise ValueError('World name must be a nonempty file name without separators.')
        if key == 'TMOD_LANGUAGE' and not re.fullmatch(r'[A-Za-z]{2,3}(-[A-Za-z0-9]+)*', value):
            raise ValueError('Language must be a code such as en-US.')
        if key == 'TMOD_MODS':
            items = [part.strip() for part in value.split(',') if part.strip()]
            if len(items) > 1000 or any(not re.fullmatch(r'(collection:)?[1-9][0-9]{0,19}', item) for item in items):
                raise ValueError('Mods must be Workshop IDs or collection:ID entries (maximum 1000).')
            value = ','.join(dict.fromkeys(items))
        output[key] = value
    return output


def web_mode():
    return os.environ.get('TMOD_CONFIG_SOURCE', 'env') == 'web'


def effective():
    return clean_mod_selection({key: os.environ[key] for key in KEYS if key in os.environ})


def clean_mod_selection(values, removed=None):
    values = dict(values)
    if 'TMOD_MODS' not in values:
        return values
    kept = []
    for entry in values['TMOD_MODS'].split(','):
        entry = entry.strip()
        if not entry:
            continue
        client = False
        if re.fullmatch(r'[1-9][0-9]{0,19}', entry):
            metadata = DATA / 'steamMods/steamapps/workshop/content/1281930' / entry / 'workshop.json'
            try:
                tags = {tag.casefold() for tag in read_json(metadata).get('Tags', []) if isinstance(tag, str)}
                client = 'client' in tags and not tags.intersection({'both', 'server'})
            except (OSError, ValueError, AttributeError, TypeError):
                pass
        if not client:
            kept.append(entry)
        elif removed is not None:
            names = sorted({path.stem for path in metadata.parent.rglob('*.tmod')})
            removed.extend(names or [f'Workshop mod {entry} (name unavailable)'])
    values['TMOD_MODS'] = ','.join(kept)
    return values


def record_removed(names):
    request_id = os.environ.get('TMOD_ADMIN_REQUEST_ID')
    if not request_id or not names:
        return
    path = RUNTIME / 'admin-removed'
    report = read_json(path)
    if report.get('id') == request_id:
        atomic_json(path, {'id': request_id, 'names': sorted(set(report.get('names', []) + names))})


def boot_values():
    # Compose seeds absent fields; saved values (including empty strings) win.
    values = clean_mod_selection(validate({**effective(), **read_json(ACTIVE)}))
    atomic_json(ACTIVE, values)
    return values


def exports(values):
    return '\n'.join(f'export {key}={shlex.quote(value)}' for key, value in validate(values).items()) + '\n'


def main(command):
    if command == 'boot':
        mode = os.environ.get('TMOD_CONFIG_SOURCE', 'env')
        if mode not in ('env', 'web'):
            raise ValueError('TMOD_CONFIG_SOURCE must be env or web.')
        if web_mode() and os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1'):
            raise ValueError('Web-managed settings cannot be combined with TMOD_USECONFIGFILE.')
        print(exports(boot_values() if web_mode() else {}), end='')
    elif command == 'snapshot':
        atomic_json(RUNTIME / 'admin-effective.json', effective())
        if web_mode():
            atomic_json(ACTIVE, effective())
            if PENDING.exists():
                atomic_json(PENDING, clean_mod_selection(read_json(PENDING)))
    elif command == 'apply':
        if not web_mode():
            raise ValueError('Settings are environment-managed.')
        removed = []
        values = clean_mod_selection(validate(read_json(PENDING)), removed)
        record_removed(removed)
        if not PENDING.exists():
            raise ValueError('No staged settings to apply.')
        environment = dict(os.environ)
        environment.update(values)
        # Retain the generated password without publishing it to the API or
        # keeping it in the supervisor/game environment.
        config = Path('/terraria-server/serverconfig.txt')
        password = next((line.partition('=')[2] for line in config.read_text().splitlines()
                         if line.startswith('password=')), '')
        environment['TMOD_PASS'] = password
        # Compose mounts /tmp as tmpfs; atomic replacement must stay on the
        # destination filesystem rather than staging in the runtime directory.
        environment['TMOD_CONFIG_PATH'] = str(config.with_name('.admin-serverconfig.txt'))
        subprocess.run(['/terraria-server/prepare-config.sh'], env=environment, check=True)
        os.replace(environment['TMOD_CONFIG_PATH'], config)
        atomic_json(ACTIVE, values)
        (RUNTIME / 'admin.env').write_text(exports(values))
    else:
        raise ValueError('Unknown admin settings command.')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as error:
        print(f'[ADMIN] {error}', file=sys.stderr)
        sys.exit(1)
