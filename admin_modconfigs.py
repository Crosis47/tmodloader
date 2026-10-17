"""Read and atomically edit existing tModLoader text configuration files."""
import configparser
import os
from pathlib import Path
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import yaml
import hashlib
import json
import re
import base64
import difflib
from datetime import datetime, timezone

import admin_settings as settings

LIMIT = 4 * 1024 * 1024
# JSON can escape each input byte as six ASCII characters, plus request metadata.
REQUEST_LIMIT = 6 * LIMIT + 65536
MERGE_REQUEST_LIMIT = 18 * LIMIT + 65536
FORMATS = {'.json': 'JSON', '.yaml': 'YAML', '.yml': 'YAML', '.toml': 'TOML', '.ini': 'INI', '.xml': 'XML'}
EXTRA_EXTENSIONS = set(FORMATS) | {'.cfg', '.conf', '.properties', '.txt'}
EXCLUDED_DIRECTORIES = {'worlds', 'players', 'mods', 'modsources', 'modreader', 'logs', 'resourcepacks', 'captures', 'wavebanks'}
EXCLUDED_FILES = {'config.json', 'input profiles.json', 'favorites.json', 'banlist.txt', 'serverconfig.txt'}


class ConflictError(ValueError):
    def __init__(self, current):
        super().__init__('This file changed on disk. Compare the latest version with your edits before saving.')
        self.current = current


def file_format(name):
    return FORMATS.get(Path(name).suffix.lower(), 'Text')


def parse_json_object(content):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + repr(key))
            result[key] = value
        return result
    value = json.loads(content, object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite numbers are not JSON.')))
    if not isinstance(value, dict):
        raise ValueError('Mod configuration must be a JSON object.')
    return value


def validate_content(name, content):
    validate_text(content)
    if re.search(r'(?m)^(?:<<<<<<< YOUR EDITS|>>>>>>> DISK VERSION)\r?$', content):
        raise ValueError('Resolve the marked merge conflicts before reviewing or saving this file.')
    kind = file_format(name)
    try:
        if kind == 'JSON':
            parse_json_object(content)
        elif kind == 'YAML':
            yaml.safe_load(content)
        elif kind == 'TOML':
            tomllib.loads(content)
        elif kind == 'INI':
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string(content)
        elif kind == 'XML':
            if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():
                raise ValueError('XML document types and entities are not supported.')
            ET.fromstring(content)
    except (ValueError, RecursionError, configparser.Error, yaml.YAMLError, ET.ParseError) as error:
        raise ValueError(f'Invalid {kind}: {error}') from error
    return {'format': kind, 'checked': kind != 'Text'}


def validate_text(content):
    if not isinstance(content, str) or len(content.encode('utf-8')) > LIMIT:
        raise ValueError('Provide UTF-8 text up to 4 MiB.')
    if any(ord(char) < 32 and char not in '\t\r\n' for char in content):
        raise ValueError('Binary/control characters cannot be edited.')



def directory():
    root = settings.DATA / 'tModLoader'
    if any(path.is_symlink() or path.is_junction() for path in (settings.DATA, root)):
        raise ValueError('Linked configuration directories cannot be edited.')
    return root


def editable_name(name):
    parts = name.split('/')
    if any(part.startswith('.') for part in parts):
        return False
    if parts[0] == 'ModConfigs':
        return True
    return (parts[0].casefold() not in EXCLUDED_DIRECTORIES
            and (len(parts) > 1 or name.casefold() not in EXCLUDED_FILES)
            and Path(name).suffix.lower() in EXTRA_EXTENSIONS)


def path_for(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name) or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Select an existing configuration file.')
    root = directory()
    if not editable_name(name):
        raise ValueError('Select an existing mod configuration file.')
    path = root
    for part in name.split('/'):
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError('Linked configuration paths cannot be edited.')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Configuration path must stay inside tModLoader.')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Configuration file is missing or linked. Refresh the list.')
    return path


def read(name):
    path = path_for(name)
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError(f'Configuration exceeds the 4 MiB editor limit. Edit {path} directly in the mounted data storage while the game is stopped, then restart the game.')
    try:
        content = data.decode('utf-8-sig')
    except UnicodeError as error:
        raise ValueError('Only UTF-8 text configuration files can be edited.') from error
    if any(ord(char) < 32 and char not in '\t\r\n' for char in content):
        raise ValueError('Binary files cannot be edited.')
    return {'name': name, 'content': content, 'format': file_format(name), 'revision': hashlib.sha256(data).hexdigest(),
            'can_restore': history_path(name).is_file()}



def inventory():
    root = directory()
    files = []
    for parent, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories
                          if not name.startswith('.')
                          and not (Path(parent) == root and name.casefold() in EXCLUDED_DIRECTORIES)
                          and not (Path(parent) / name).is_symlink()
                          and not (Path(parent) / name).is_junction()]
        for name in names:
            relative = (Path(parent) / name).relative_to(root).as_posix()
            try:
                path_for(relative)
            except (OSError, ValueError):
                continue
            files.append(relative)
    return {'files': sorted(files, key=lambda name: (name.casefold(), name))}


def history_path(name, create=False):
    root = settings.DATA
    for part in ('admin', 'mod-config-history'):
        root = root / part
        if root.is_symlink() or root.is_junction():
            raise ValueError('Linked configuration history cannot be used.')
        if create:
            root.mkdir(mode=0o700, exist_ok=True)
    path = root / (hashlib.sha256(name.encode('utf-8')).hexdigest() + '.json')
    if path.is_symlink() or path.is_junction():
        raise ValueError('Linked configuration history cannot be used.')
    return path


def previous(name):
    path_for(name)
    path = history_path(name)
    try:
        with path.open('rb') as stream:
            raw = stream.read(2 * LIMIT + 65536)
        record = json.loads(raw)
        data = base64.b64decode(record['data'], validate=True)
        if (record['name'] != name or len(data) > LIMIT
                or hashlib.sha256(data).hexdigest() != record['revision']):
            raise ValueError('Invalid history record.')
        content = data.decode('utf-8-sig')
        if any(ord(char) < 32 and char not in '\t\r\n' for char in content):
            raise ValueError('Invalid history text.')
        return {'name': name, 'content': content, 'revision': record['revision'],
                'saved_at': record['saved_at'], 'history_revision': hashlib.sha256(raw).hexdigest(),
                'data': data}
    except FileNotFoundError as error:
        raise ValueError('No previous version is available for this file.') from error
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise ValueError('Configuration history is damaged; the file has not been changed.') from error


def change_preview(before, after):
    # Bound comparison work; large files remain available in the comparison panes.
    if max(len(before), len(after)) > 128 * 1024:
        return {'diff': None, 'diff_limited': True}
    old, new = (text.replace('\r\n', '\n').replace('\r', '\n').splitlines(keepends=True)
                for text in (before, after))
    if max(len(old), len(new)) > 2000:
        return {'diff': None, 'diff_limited': True}
    chunks, length = [], 0
    for chunk in difflib.unified_diff(old, new, fromfile='On disk', tofile='Proposed', n=3):
        length += len(chunk)
        if length > 256 * 1024:
            return {'diff': None, 'diff_limited': True}
        chunks.append(chunk if chunk.endswith('\n') else chunk + '\n\\ No newline at end of file\n')
    return {'diff': ''.join(chunks), 'diff_limited': False}


def preview(payload):
    current = read(payload.get('name'))
    restoring = payload.get('action') == 'restore'
    target = previous(current['name']) if restoring else None
    content = target['content'] if target else payload.get('content')
    if not restoring:
        validate_content(current['name'], content)
    disk_content = payload.get('disk_content', current['content'])
    if 'disk_content' in payload:
        if payload.get('disk_revision') != current['revision']:
            raise ConflictError(current)
        validate_content(current['name'], disk_content)
    disk_error = None
    if not restoring:
        try:
            validate_content(current['name'], disk_content)
        except ValueError as error:
            disk_error = str(error)
    return {'current': current, 'content': content, 'action': 'restore' if restoring else 'save',
            'conflict': current['revision'] != payload.get('revision'),
            'disk_error': disk_error,
            'history_revision': target['history_revision'] if target else None,
            'saved_at': target['saved_at'] if target else None,
            **({'diff': None, 'diff_limited': True} if disk_error else change_preview(disk_content, content))}


def combine_json(base, draft, disk, selections):
    """Merge JSON settings by value. Arrays remain single values to preserve order."""
    versions = []
    for label, text in (('Originally loaded version', base), ('Your draft', draft), ('Disk version', disk)):
        try:
            versions.append(parse_json_object(text))
        except (ValueError, RecursionError) as error:
            raise ValueError(f'{label} is not valid JSON: {error}. Combining is paused. Your draft is preserved.') from error
    original, mine, theirs = versions
    if max(len(text) for text in (base, draft, disk)) > 128 * 1024:
        return {'content': draft, 'conflicts': 0, 'choices': [], 'unresolved': 0,
                'skipped': 0, 'manual': True, 'kind': 'json'}
    missing = object()
    decisions, skipped = [], 0

    def same(first, second):
        if type(first) is not type(second):
            return False
        if isinstance(first, dict):
            return first.keys() == second.keys() and all(same(value, second[key]) for key, value in first.items())
        if isinstance(first, list):
            return len(first) == len(second) and all(same(a, b) for a, b in zip(first, second))
        return first == second

    def display(value):
        return '(Removed)' if value is missing else json.dumps(value, ensure_ascii=False, indent=2)

    def combine(old, ours, current, path):
        nonlocal skipped
        if same(ours, current):
            if not same(old, ours):
                skipped += 1
            return current
        if same(ours, old):
            return current
        if same(current, old):
            return ours
        if isinstance(ours, dict) and isinstance(current, dict) and (isinstance(old, dict) or old is missing):
            before = old if isinstance(old, dict) else {}
            result = {}
            for key in dict.fromkeys([*current, *ours, *before]):
                value = combine(before.get(key, missing), ours.get(key, missing), current.get(key, missing), path + [key])
                if value is not missing:
                    result[key] = value
            return result
        identifier = str(len(decisions))
        choice = selections.get(identifier)
        pointer = '/' + '/'.join(key.replace('~', '~0').replace('/', '~1') for key in path)
        decisions.append({'id': identifier, 'label': 'Setting ' + pointer, 'mine': display(ours),
                          'disk': display(current), 'original': display(old), 'selected': choice})
        return ours if choice == 'mine' else current

    result = combine(original, mine, theirs, [])
    # Keep disk formatting exactly when there are no remaining changes to apply.
    content = disk if same(result, theirs) else json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    return {'content': content, 'conflicts': len(decisions), 'choices': decisions, 'skipped': skipped,
            'unresolved': sum(choice['selected'] is None for choice in decisions), 'manual': False, 'kind': 'json'}


def combine_edits(base, draft, disk, name='', selections=None):
    """Skip shared edits and ask for explicit choices only where values differ."""
    selections = selections or {}
    base, draft, disk = (text.replace('\r\n', '\n').replace('\r', '\n') for text in (base, draft, disk))
    if file_format(name) == 'JSON':
        try:
            return combine_json(base, draft, disk, selections)
        except RecursionError as error:
            raise ValueError('JSON nesting is too deep to combine safely. Your draft is preserved.') from error
    def clean(content, skipped=0):
        return {'content': content, 'conflicts': 0, 'choices': [], 'unresolved': 0,
                'skipped': skipped, 'manual': False, 'kind': 'text'}
    if draft == disk:
        return clean(disk, int(draft != base))
    if disk == base:
        return clean(draft)
    if draft == base:
        return clean(disk)
    if max(len(text) for text in (base, draft, disk)) > 128 * 1024:
        return {**clean(draft), 'manual': True}
    original, mine, theirs = (text.splitlines(keepends=True) for text in (base, draft, disk))
    if max(len(lines) for lines in (original, mine, theirs)) > 2000:
        return {**clean(draft), 'manual': True}
    edits = []
    for side, lines in enumerate((mine, theirs)):
        for tag, start, end, other_start, other_end in difflib.SequenceMatcher(None, original, lines).get_opcodes():
            if tag == 'replace' and end - start == other_end - other_start:
                # Separate adjacent setting changes so shared lines can be skipped.
                edits.extend((left, left + 1, [lines[right]], side)
                             for left, right in zip(range(start, end), range(other_start, other_end)))
            elif tag != 'equal':
                edits.append((start, end, lines[other_start:other_end], side))
    edits.sort(key=lambda edit: (edit[0], edit[1]))

    def overlaps(first, second):
        start, end, *_ = first
        other_start, other_end, *_ = second
        if start == end and other_start == other_end:
            return start == other_start
        if start == end:
            return other_start < start < other_end
        if other_start == other_end:
            return start < other_start < end
        return start < other_end and other_start < end

    groups = []
    for edit in edits:
        if groups and any(overlaps(edit, existing) for existing in groups[-1]):
            groups[-1].append(edit)
        else:
            groups.append([edit])
    output, cursor, decisions, skipped = [], 0, [], 0
    for group in groups:
        start = min(edit[0] for edit in group)
        end = max(edit[1] for edit in group)
        output.extend(original[cursor:start])
        versions = []
        for side in (0, 1):
            lines, position = [], start
            for left, right, replacement, owner in group:
                if owner == side:
                    lines.extend(original[position:left])
                    lines.extend(replacement)
                    position = right
            lines.extend(original[position:end])
            versions.append(lines)
        mine, theirs = versions
        if mine == theirs:
            output.extend(theirs)
            skipped += 1
        elif theirs == original[start:end]:
            output.extend(mine)
        elif mine == original[start:end]:
            output.extend(theirs)
        else:
            identifier = str(len(decisions))
            choice = selections.get(identifier)
            decisions.append({'id': identifier, 'label': 'Original lines ' + str(start + 1) + '–' + str(max(start + 1, end)),
                              'mine': ''.join(mine) or '(Removed)', 'disk': ''.join(theirs) or '(Removed)',
                              'original': ''.join(original[start:end]) or '(Empty)', 'selected': choice})
            output.extend(mine if choice == 'mine' else theirs)
        cursor = end
    output.extend(original[cursor:])
    return {'content': ''.join(output), 'conflicts': len(decisions), 'choices': decisions, 'skipped': skipped,
            'unresolved': sum(choice['selected'] is None for choice in decisions), 'manual': False, 'kind': 'text'}


def merge(payload):
    current = read(payload.get('name'))
    if current['revision'] != payload.get('revision'):
        raise ConflictError(current)
    base, draft = payload.get('base_content'), payload.get('content')
    validate_text(base)
    validate_content(current['name'], draft)
    disk_content = payload.get('disk_content', current['content'])
    validate_text(disk_content)
    if 'disk_content' in payload:
        try:
            validate_content(current['name'], disk_content)
        except ValueError as error:
            raise ValueError('Disk corrections are invalid: ' + str(error)) from error
    selections = payload.get('choices', {})
    if not isinstance(selections, dict) or any(not isinstance(key, str) or value not in ('mine', 'disk') for key, value in selections.items()):
        raise ValueError('Choose your edit or the disk value for each remaining difference.')
    result = combine_edits(base, draft, disk_content, current['name'], selections)
    if payload.get('resolve') and result['unresolved']:
        raise ValueError('Choose a version for every remaining difference before continuing.')
    if set(selections) - {choice['id'] for choice in result['choices']}:
        raise ValueError('The merge choices changed. Compare the file again.')
    return {'current': current, **result}


def atomic_bytes(path, data):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.admin-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_version(current, data):
    path = path_for(current['name'])
    with path.open('rb') as stream:
        old = stream.read(LIMIT + 1)
    if hashlib.sha256(old).hexdigest() != current['revision']:
        raise ConflictError(read(current['name']))
    history = history_path(current['name'], create=True)
    if history.exists():
        with history.open('rb') as stream:
            old_history = stream.read(2 * LIMIT + 65536)
    else:
        old_history = None
    record = {'name': current['name'], 'revision': current['revision'],
              'saved_at': datetime.now(timezone.utc).isoformat(), 'data': base64.b64encode(old).decode('ascii')}
    atomic_bytes(history, json.dumps(record).encode('utf-8'))
    try:
        latest = read(current['name'])
        if latest['revision'] != current['revision']:
            raise ConflictError(latest)
        atomic_bytes(path_for(current['name']), data)
    except Exception:
        if old_history is None:
            history.unlink()
        else:
            atomic_bytes(history, old_history)
        raise
    return read(current['name'])


def save(payload):
    current = read(payload.get('name'))
    content = payload.get('content')
    validate_content(current['name'], content)
    if current['revision'] != payload.get('revision'):
        raise ConflictError(current)
    if content == current['content'].replace('\r\n', '\n').replace('\r', '\n') or content == current['content']:
        return current
    return write_version(current, content.encode('utf-8'))


def restore(payload):
    current = read(payload.get('name'))
    if payload.get('confirm') is not True:
        raise ValueError('Review and confirm the previous version before restoring.')
    if current['revision'] != payload.get('revision'):
        raise ConflictError(current)
    target = previous(current['name'])
    if payload.get('history_revision') != target['history_revision']:
        raise ValueError('The previous version changed. Review it again before restoring.')
    return write_version(current, target['data'])
