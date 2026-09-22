"""Backup summaries and conservative preparation for a different container build."""
import datetime
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import uuid

import backup

RUNTIME_FILE = Path('/terraria-server/backup-runtime.json')
BUILD_FILE = Path('/terraria-server/backup-build-id')


def current_runtime():
    if RUNTIME_FILE == Path('/terraria-server/backup-runtime.json'):
        import admin_updates
        return admin_updates.runtime()
    try:
        value = json.loads(RUNTIME_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def current_build():
    try:
        value = BUILD_FILE.read_text().strip()
        if BUILD_FILE == Path('/terraria-server/backup-build-id'):
            import admin_updates
            import hashlib
            selected = admin_updates.read(admin_updates.ROOT / 'active.json')
            if selected:
                value = hashlib.sha256((value + json.dumps(selected, sort_keys=True)).encode()).hexdigest()
        return value
    except OSError:
        return None


def version(value):
    if isinstance(value, str) and re.fullmatch(r'v?\d+(?:\.\d+){3}', value):
        return tuple(int(part) for part in value.lstrip('v').split('.'))
    return None


def summarize_archive(archive):
    worlds, enabled, workshop, settings = [], [], [], {}
    files = size = world_count = 0
    logged_version = None
    has_settings = has_logs = has_mod_config = False
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if not member.isfile():
                continue
            files += 1
            size += member.size
            name = member.name
            if name.startswith('data/tModLoader/Worlds/') and name.endswith('.wld'):
                world_count += 1
                if len(worlds) < 100:
                    worlds.append(PurePosixPath(name).name[:128])
            has_logs |= name.startswith('data/tModLoader/Logs/')
            has_mod_config |= '/ModConfigs/' in name
            if name in ('data/admin/settings.json', 'data/tModLoader/Mods/enabled.json') and member.size <= 65536:
                with tar.extractfile(member) as stream:
                    try:
                        value = json.loads(stream.read())
                    except (ValueError, UnicodeError):
                        continue
                if name.endswith('settings.json'):
                    if not isinstance(value, dict):
                        continue
                    settings = value
                    has_settings = True
                elif isinstance(value, list):
                    enabled = [item[:128] for item in value if isinstance(item, str)]
            if name == 'data/tModLoader/Logs/server.log':
                with tar.extractfile(member) as stream:
                    text = stream.read(65536).decode('utf-8', errors='replace')
                match = re.search(r'Starting tModLoader server \d+(?:\.\d+){3}\+(\d+(?:\.\d+){3})\|', text)
                if match:
                    logged_version = match[1]
    active = settings.get('TMOD_WORLDNAME')
    selection = settings.get('TMOD_MODS', '')
    if isinstance(selection, str):
        workshop = [entry.strip() for entry in selection.split(',') if entry.strip()]
    return {'active_world': active[:256] if isinstance(active, str) else None,
            'active_world_source': 'Saved dashboard settings' if active else 'Not recorded',
            'worlds': sorted(worlds)[:100], 'world_count': world_count,
            'enabled_mods': enabled[:100], 'enabled_mod_count': len(enabled),
            'workshop': [item[:128] for item in workshop[:100]], 'workshop_count': len(workshop),
            'unpacked_bytes': size, 'file_count': files, 'has_settings': has_settings,
            'has_logs': has_logs, 'has_mod_config': has_mod_config,
            'tmodloader_version': logged_version}


def compatibility(metadata, runtime=None, build=None):
    runtime = current_runtime() if runtime is None else runtime
    build = current_build() if build is None else build
    result = {'can_prepare': False, 'matches_current': False}
    if metadata.get('format') != 1:
        return {**result, 'detail': 'Unsupported archive format; keep the original backup.'}
    if build and metadata.get('image_id') == build:
        return {**result, 'matches_current': True, 'detail': 'Matches the current container build.'}
    if not build:
        return {**result, 'detail': 'Current container build identity is unavailable.'}
    source = metadata.get('runtime') or {}
    if not isinstance(source, dict) or not isinstance(metadata.get('snapshot', {}), dict):
        return {**result, 'detail': 'Invalid backup summary; automatic preparation is unavailable.'}
    old_version = source.get('tmodloader_version') or (metadata.get('snapshot') or {}).get('tmodloader_version')
    if not version(old_version) or not version(runtime.get('tmodloader_version')):
        return {**result, 'detail': 'Different container build. Inspect this backup to check its tModLoader version; unknown versions require the original image.'}
    if version(old_version) != version(runtime['tmodloader_version']):
        return {**result, 'detail': f"Requires tModLoader {old_version}; current release is {runtime['tmodloader_version']}. Automatic game-version conversion is not supported. Keep or use the matching image."}
    if source.get('tmodloader_sha256') and source['tmodloader_sha256'] != runtime.get('tmodloader_sha256'):
        return {**result, 'detail': 'The tModLoader binaries differ despite their version labels. Use the original image.'}
    return {**result, 'can_prepare': True,
            'detail': 'Same tModLoader release, different container build. A verified copy can be prepared for this container; the original is preserved.'}


def inspect_archive(bundle):
    metadata = backup.validate(bundle)
    # Read actual archived files, including for legacy manifests without summaries.
    snapshot = summarize_archive(bundle / 'data.tar.gz')
    recorded = metadata.get('snapshot') or {}
    if recorded.get('active_world_source') == 'Running settings at backup':
        snapshot.update({key: recorded.get(key) for key in ('active_world', 'active_world_source', 'workshop', 'workshop_count')})
    metadata = {**metadata, 'snapshot': snapshot}
    return {**metadata, 'archive': bundle.name, 'compatibility': compatibility(metadata), 'verified': True}


def prepare(bundle, destination, expected, reserve=0):
    details = inspect_archive(bundle)
    if details['sha256'] != expected:
        raise ValueError('Archive changed since inspection. Inspect it again before preparing a copy.')
    if not details['compatibility']['can_prepare']:
        raise ValueError(details['compatibility']['detail'])
    required = (bundle / 'data.tar.gz').stat().st_size + 65536
    if shutil.disk_usage(destination).free < required + reserve:
        raise ValueError('Insufficient backup storage for a prepared copy and the configured free-space reserve.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    final = destination / f'tmod-backup-{stamp}-{uuid.uuid4().hex[:8]}'
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=destination) as temporary:
        stage = Path(temporary)
        shutil.copyfile(bundle / 'data.tar.gz', stage / 'data.tar.gz')
        metadata = {key: value for key, value in details.items() if key not in ('archive', 'compatibility', 'verified')}
        metadata.update(image_id=current_build(), image_reference='container-build-fingerprint', runtime=current_runtime(),
                        prepared_from={'archive': bundle.name, 'image_id': details['image_id'],
                                       'sha256': details['sha256'], 'runtime': details.get('runtime'), 'prepared_at': stamp})
        (stage / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        backup.validate(stage)
        for path in stage.iterdir():
            with path.open('r+b') as stream:
                os.fsync(stream.fileno())
        backup.sync_directory(stage)
        stage.rename(final)
        backup.sync_directory(destination)
    return {'archive': final.name, 'original': bundle.name, 'sha256': details['sha256']}
