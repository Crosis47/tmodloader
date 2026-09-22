"""Cached, read-only upstream release discovery and runtime update status."""
import datetime
import json
import os
from pathlib import Path
import re
import threading
import subprocess
import time
import urllib.request

import admin_settings as settings

BASE = Path('/terraria-server')
ROOT = settings.DATA / '.tmod-control/updates'
CHECK_LOCK = threading.Lock()
CONTAINER_LOCK = threading.Lock()
CHECKS_ENABLED = False
BUSY = frozenset(('initializing', 'checking', 'downloading', 'staging', 'testing', 'recovering', 'awaiting_start'))
RELEASES = 'https://api.github.com/repos/tModLoader/tModLoader/releases?per_page=100'
TAG = re.compile(r'v[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3}')


def container_status():
    """Check this container project's published releases, independently of tML."""
    installed = (BASE / 'VERSION').read_text().strip()
    selected_channel = read(BASE / 'backup-runtime.json').get('update_channel', 'stable')
    cache_path = ROOT / 'container-check.json'
    with CONTAINER_LOCK:
        cached = read(cache_path)
        if (cached.get('channel') != selected_channel or
                time.time() - cached.get('attempted', 0) >= (900 if cached.get('error') else 21600)):
            try:
                request = urllib.request.Request('https://api.github.com/repos/Crosis47/tmodloader/releases?per_page=100',
                                                 headers={'User-Agent': 'tmodloader-container-updates', 'Accept': 'application/vnd.github+json'})
                with urllib.request.urlopen(request, timeout=8) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError('Release response exceeds the size limit.')
                candidates = []
                for item in json.loads(raw):
                    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(-preview)?', item.get('tag_name', ''))
                    if item.get('draft') or not match:
                        continue
                    if bool(match[4]) != (selected_channel == 'preview') or (selected_channel == 'stable' and item.get('prerelease')):
                        continue
                    candidates.append((tuple(map(int, match.group(1, 2, 3))), item['tag_name']))
                if not candidates:
                    raise ValueError('No published container release found for this channel.')
                latest = max(candidates)[1]
                cached = {'latest': latest, 'channel': selected_channel, 'attempted': time.time(), 'error': ''}
            except (OSError, ValueError, TypeError, KeyError) as error:
                cached = {'channel': selected_channel, 'attempted': time.time(), 'error': str(error)[:200]}
            settings.atomic_json(cache_path, cached)
    current = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', installed)
    latest = cached.get('latest', '')
    available = bool(current and latest and not cached.get('error') and
                     tuple(map(int, latest.removesuffix('-preview').split('.'))) > tuple(map(int, current.groups())))
    return {'installed': installed, 'latest': latest, 'available': available, 'channel': selected_channel,
            'url': 'https://github.com/Crosis47/tmodloader/releases/tag/' + latest if latest else '',
            'error': cached.get('error', '')}


def read(path):
    try:
        return settings.read_json(path)
    except (OSError, ValueError):
        return {}


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def version(tag):
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ValueError('Expected an exact modern tModLoader tag, for example v2026.07.3.0.')
    return tuple(map(int, tag[1:].split('.')))


def active():
    selected = read(ROOT / 'active.json')
    tag = selected.get('tmodloader_version')
    if tag:
        version(tag)
        directory = ROOT / 'releases' / tag
        if directory.is_symlink() or not (directory / 'tModLoader.dll').is_file():
            raise ValueError('Selected runtime is missing. Restore its cached files before starting.')
        return directory
    return BASE


def runtime():
    base = read(BASE / 'backup-runtime.json')
    selected = read(ROOT / 'active.json')
    return {**base, **selected, 'container_version': base.get('container_version', 'development')}


def channel():
    value = os.environ.get('TMOD_UPDATE_CHANNEL') or read(BASE / 'backup-runtime.json').get('update_channel', 'stable')
    if value not in ('stable', 'preview'):
        raise ValueError('TMOD_UPDATE_CHANNEL must be stable or preview.')
    return value


def release(item, selected_channel):
    """Track the supported Terraria branch; never select legacy/prerelease by accident."""
    tag = item.get('tag_name', '')
    name = item.get('name', '')
    if item.get('draft') or not TAG.fullmatch(tag):
        return None
    branch = 'refs/heads/' + selected_channel
    if not name.startswith('1.4.4-') or branch not in name:
        return None
    if selected_channel == 'stable' and item.get('prerelease'):
        return None
    url = f'https://github.com/tModLoader/tModLoader/releases/download/{tag}/tModLoader.zip'
    asset = next((a for a in item.get('assets', []) if a.get('name') == 'tModLoader.zip'
                  and a.get('browser_download_url') == url), None)
    if not asset:
        return None
    return {'version': tag, 'url': f'https://github.com/tModLoader/tModLoader/releases/tag/{tag}',
            'download': url, 'size': asset.get('size', 0), 'digest': asset.get('digest'),
            'channel': selected_channel, 'published': item.get('published_at')}


def check():
    selected_channel = channel()
    old = read(ROOT / 'check.json')
    try:
        request = urllib.request.Request(RELEASES, headers={'User-Agent': 'tmodloader-container-updates',
                                                          'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Release response exceeds the size limit.')
        candidates = [candidate for item in json.loads(raw) if (candidate := release(item, selected_channel))]
        if not candidates:
            raise ValueError('No supported release found for this channel.')
        result = {'latest': max(candidates, key=lambda c: version(c['version'])), 'checked_at': stamp(),
                  'attempted': time.time(), 'channel': selected_channel, 'error': ''}
    except (OSError, ValueError, TypeError, KeyError) as error:
        result = {**(old if old.get('channel') == selected_channel else {}), 'attempted': time.time(),
                  'channel': selected_channel, 'error': 'Release check failed; keeping installed files. ' + str(error)[:200]}
    settings.atomic_json(ROOT / 'check.json', result)
    return result


def pinned_release(tag):
    version(tag)
    request = urllib.request.Request('https://api.github.com/repos/tModLoader/tModLoader/releases/tags/' + tag,
                                     headers={'User-Agent': 'tmodloader-container-updates'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Pinned release response exceeds the size limit.')
    candidate = release(json.loads(raw), channel())
    if not candidate or candidate['version'] != tag:
        raise ValueError('Pinned release is not available on the selected supported channel.')
    return candidate


def request_check(force=False):
    if not CHECKS_ENABLED:
        return
    cached = read(ROOT / 'check.json')
    age = time.time() - cached.get('attempted', 0)
    if cached.get('channel') == channel() and age < (60 if force else (900 if cached.get('error') else 21600)):
        return
    if not CHECK_LOCK.acquire(blocking=False):
        return

    def worker():
        try:
            check()
        finally:
            CHECK_LOCK.release()
    threading.Thread(target=worker, daemon=True).start()


def status(refresh=True):
    if refresh:
        request_check()
    cached = read(ROOT / 'check.json')
    installed = runtime().get('tmodloader_version')
    latest = cached.get('latest') if cached.get('channel') == channel() else None
    newer = bool(latest and installed and version(latest['version']) > version(installed))
    checkpoint = read(ROOT / 'checkpoint.json').get('id')
    previous = read(ROOT / 'transactions' / checkpoint / 'manifest.json') if isinstance(checkpoint, str) and re.fullmatch('[a-f0-9]{32}', checkpoint) else {}
    return {'installed': installed, 'channel': channel(), 'latest': latest,
            'announcements': announcements_enabled(),
            'available': newer, 'checked_at': cached.get('checked_at'), 'error': cached.get('error', ''),
            'checking': CHECK_LOCK.locked(), 'operation': read(ROOT / 'status.json'),
            'automatic': os.environ.get('TMOD_AUTO_UPDATE', '1') == '1',
            'pin': os.environ.get('TMOD_UPDATE_VERSION', ''),
            'hold': read(ROOT / 'hold.json').get('version', ''),
            'rollback_available': bool(previous), 'checkpoint_created': previous.get('created'),
            'checkpoint_id': checkpoint if previous else None,
            'previous_version': previous.get('runtime', {}).get('tmodloader_version'),
            'rollback_pending': (ROOT / 'rollback-request.json').exists(),
            'diagnostics_available': any(p.is_file() and not p.is_symlink() and p.stat().st_size
                                         for p in diagnostic_paths())}


def announcements_enabled():
    return read(ROOT / 'announcements.json').get('enabled', False) is True


def announce_available():
    """Called by the admin worker while no game-changing operation is active."""
    if not announcements_enabled():
        return
    request_check()
    state = status(refresh=False)
    if not state['available'] or state['error'] or state['operation'].get('state') in BUSY:
        return
    tag = state['latest']['version']
    version(tag)
    notice = read(ROOT / 'announced.json')
    if notice.get('version') == tag and notice.get('channel') == state['channel']:
        return
    if subprocess.run(['healthcheck'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode:
        return
    result = subprocess.run(['inject', 'say A new tModLoader version (' + tag + ') is available. An administrator can update it from the dashboard.'],
                            capture_output=True, timeout=10)
    if result.returncode == 0:
        settings.atomic_json(ROOT / 'announced.json', {'version': tag, 'channel': state['channel'], 'sent_at': stamp()})


def diagnostic_paths():
    identity = read(ROOT / 'status.json').get('checkpoint')
    paths = [ROOT / 'dotnet-install.log']
    if isinstance(identity, str) and re.fullmatch('[a-f0-9]{32}', identity):
        paths += [ROOT / 'transactions' / identity / name for name in ('workshop.log', 'compatibility.log', 'compatibility-server.log')]
    return paths


def diagnostics():
    output = []
    for path in diagnostic_paths():
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 16384))
                output.append(path.name + '\n' + stream.read(16384).decode('utf-8', errors='replace'))
    return {'output': '\n\n'.join(output) or 'No log output recorded for this update.'}
