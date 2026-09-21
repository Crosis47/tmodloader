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

import admin_settings as settings

LIMIT = 48 * 1024
FORMATS = {'.json': 'JSON', '.yaml': 'YAML', '.yml': 'YAML', '.toml': 'TOML', '.ini': 'INI', '.xml': 'XML'}


def file_format(name):
    return FORMATS.get(Path(name).suffix.lower(), 'Text')


def validate_content(name, content):
    if not isinstance(content, str) or len(content.encode('utf-8')) > LIMIT:
        raise ValueError('Provide UTF-8 text up to 48 KiB.')
    if any(ord(char) < 32 and char not in '\t\r\n' for char in content):
        raise ValueError('Binary/control characters cannot be edited.')
    kind = file_format(name)
    try:
        if kind == 'JSON':
            value = json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite numbers are not JSON.')))
            if not isinstance(value, dict):
                raise ValueError('Mod configuration must be a JSON object.')
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
    except (ValueError, configparser.Error, yaml.YAMLError, ET.ParseError) as error:
        raise ValueError(f'Invalid {kind}: {error}') from error
    return {'format': kind, 'checked': kind != 'Text'}



def directory():
    root = settings.DATA / 'tModLoader/ModConfigs'
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError('Linked configuration directories cannot be edited.')
    return root


def path_for(name):
    if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name):
        raise ValueError('Select an existing configuration file.')
    path = directory() / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Configuration file is missing or linked. Refresh the list.')
    return path


def read(name):
    path = path_for(name)
    if path.stat().st_size > LIMIT:
        raise ValueError('Configuration exceeds the 48 KiB editor limit.')
    data = path.read_bytes()
    try:
        content = data.decode('utf-8-sig')
    except UnicodeError as error:
        raise ValueError('Only UTF-8 text configuration files can be edited.') from error
    if any(ord(char) < 32 and char not in '\t\r\n' for char in content):
        raise ValueError('Binary files cannot be edited.')
    return {'name': name, 'content': content, 'format': file_format(name), 'revision': hashlib.sha256(data).hexdigest()}



def inventory():
    return {'files': [p.name for p in sorted(directory().glob('*')) if p.is_file() and not p.is_symlink()]}


def save(payload):
    current = read(payload.get('name'))
    content = payload.get('content')
    validate_content(current['name'], content)
    if current['revision'] != payload.get('revision'):
        raise ValueError('This file changed. Reload it before saving.')
    path = path_for(current['name'])
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.admin-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return read(current['name'])
