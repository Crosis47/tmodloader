"""Local support reports: allowlisted metadata and sanitized error lines only."""
import datetime
import os
from pathlib import Path
import re

import admin_settings as settings
import admin_updates

TAIL_LIMIT = 128 * 1024
ERROR_LIMIT = 40
SENSITIVE = re.compile(r'pass(?:word|wd)?|secret|token|api[\s_-]*key|authorization|credential|cookie|private[\s_-]*key|connection[\s_-]*string', re.I)
ERROR = re.compile(r'\b(?:error|exception|fatal|failed|failure|traceback)\b|\w+Exception\b', re.I)


def read_tail(path):
    if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
        return '', False
    try:
        with path.open('rb') as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - TAIL_LIMIT))
            data = stream.read(TAIL_LIMIT)
        lines = data.decode('utf-8', errors='replace').splitlines()
        return '\n'.join(lines[1:] if size > TAIL_LIMIT else lines), True
    except OSError:
        return '', False


def known_private_values(token):
    values = [token]
    for key, value in os.environ.items():
        if SENSITIVE.search(key) or key in ('TMOD_PASS', 'TMOD_WORLDNAME', 'TMOD_WORLDSEED', 'TMOD_MOTD'):
            values.append(value)
    for staged in (False, True):
        try:
            values.append(settings.password_value(staged))
        except (OSError, ValueError):
            pass
    for path in (settings.ACTIVE, settings.PENDING, settings.RUNTIME / 'admin-effective.json'):
        try:
            values.extend(value for key, value in settings.read_json(path).items()
                          if key in ('TMOD_WORLDNAME', 'TMOD_WORLDSEED', 'TMOD_MOTD') or SENSITIVE.search(key))
        except (OSError, ValueError):
            pass
    # The generated config can contain a password no longer present in env.
    try:
        with Path('/terraria-server/serverconfig.txt').open() as stream:
            for line in stream:
                key, separator, value = line.strip().partition('=')
                if separator and key.lower() in ('password', 'world', 'worldname', 'seed', 'motd'):
                    values.append(value)
    except OSError:
        pass
    return sorted({value for value in values if isinstance(value, str) and value}, key=len, reverse=True)


def sanitize(text, private=()):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text))
    if SENSITIVE.search(text) or re.search(r'\b(?:player|client|chat|joining|joined|steamid)\b', text, re.I):
        return '[REDACTED: private log details]'
    for value in private:
        text = text.replace(value, '[REDACTED]')
    text = re.sub(r'https?://[^\s<>"\x27]+', '[URL]', text, flags=re.I)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[EMAIL]', text)
    text = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?![\w.])', '[IP]', text)
    text = re.sub(r'(?<!\w)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.%]*(?!\w)', '[IP]', text, flags=re.I)
    text = re.sub(r'(?i)(?:[a-z]:[\\/]|/(?:home|Users|data|tmp|terraria-server|root|mnt|app|srv|opt)/)[^\s<>"\x27]*', '[PATH]', text)
    text = re.sub(r'\\\\[^\s<>"\x27]+', '[PATH]', text)
    text = re.sub(r'\b(?:[0-9a-f]{24,}|\d{16,}|[A-Za-z0-9_+/=-]{40,})\b', '[IDENTIFIER]', text, flags=re.I)
    # Prevent log content from escaping its Markdown code block.
    text = text.replace('`', "'")
    return ''.join(char for char in text if ord(char) >= 32 or char == '\t')[:1000]


def version(value):
    return value if isinstance(value, str) and re.fullmatch(r'v?\d+(?:\.\d+){1,3}(?:-[A-Za-z0-9.-]+)?', value) else 'Unavailable'


def report(console_log, loaded_mods, token=''):
    private = known_private_values(token)
    try:
        runtime = admin_updates.runtime()
    except (OSError, ValueError):
        runtime = {}
    try:
        container = version((admin_updates.BASE / 'VERSION').read_text().strip())
    except OSError:
        container = version(runtime.get('container_version'))
    text = ['## Server support report', '', 'Generated: ' + datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'Container: ' + container, 'tModLoader: ' + version(runtime.get('tmodloader_version')),
            'Settings mode: ' + ('Web managed' if settings.web_mode() else 'Environment managed'), '', '### Enabled mods', '']
    if loaded_mods.get('available'):
        mods = loaded_mods.get('mods', [])
        text.extend('- ' + sanitize(item.get('name', ''), private) + ' (' + sanitize(item.get('internal_name', ''), private)
                    + ') ' + version(item.get('version')) for item in mods[:500])
        if not mods:
            text.append('No loaded mods reported.')
        if len(mods) > 500:
            text.append('Mod list limited to 500 entries.')
    else:
        text.append('Loaded mods unavailable: no confirmed completed mod load.')
        # A failed startup still needs a useful selection list. Distinguish
        # enabled filenames from mods actually confirmed loaded by the game.
        try:
            path = settings.DATA / 'tModLoader/Mods/enabled.json'
            if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
                raise ValueError('Linked mod list.')
            enabled = settings.read_json(path, [])
            names = [name for name in enabled if isinstance(name, str) and re.fullmatch(r'[\w.-]{1,150}', name)] if isinstance(enabled, list) else []
            if names:
                text += ['Enabled mod filenames (loading not confirmed):', *['- ' + sanitize(name, private) for name in names[:500]]]
        except (OSError, ValueError):
            pass
    text += ['', '### Recent errors', '']
    errors, available = [], False
    for path in (console_log.with_name('server.log'), console_log):
        content, found = read_tail(path)
        available |= found
        # Sanitize full lines before truncating; otherwise a secret's prefix
        # could survive just beyond the display limit.
        errors.extend(sanitize(line, private) for line in content.splitlines() if ERROR.search(line))
    errors = list(dict.fromkeys(errors))[-ERROR_LIMIT:]
    if errors:
        text += ['```text', *errors, '```']
    else:
        text.append('No error lines found in the bounded recent log tails.' if available else 'Recent logs unavailable.')
    text += ['', 'Report includes version metadata, confirmed loaded mods, and up to 40 error lines from the latest 128 KiB of each current log.',
             'Credentials, network addresses, known private values, and common personal paths are removed before preview. Configuration contents, environment dumps, and player rosters are excluded. Review before sharing.']
    return {'report': '\n'.join(text) + '\n'}
