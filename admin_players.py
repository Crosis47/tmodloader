"""Bounded, fresh native-console player queries and moderation audit records.

The native playing command reports name (remote address), followed by a count.
Version responses delimit a query without broadcasting a marker to players.
Callers serialize this module with the administration STATE_LOCK.
"""
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import stat
import sqlite3
import time

import admin_metrics
import admin_settings as settings

CACHE = None
CACHE_AT = 0.0
VERSION = re.compile(r'^: Terraria Server v[^\r\n]+ - tModLoader[^\r\n]+$', re.MULTILINE)


def line_text(value, limit=500):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f'Enter a single line of 1–{limit} characters without control characters.')
    return value


def identifier(address):
    if re.fullmatch(r'STEAM_0:[01]:[0-9]+', address):
        return address
    host, separator, port = address.rpartition(':')
    if not separator or not port.isdecimal() or not 0 < int(port) <= 65535:
        raise ValueError('Unrecognized player address.')
    return str(ipaddress.ip_address(host.strip('[]')))


def parse_roster(output):
    frames = list(VERSION.finditer(output.replace('\r', '')))
    if len(frames) < 2:
        return None
    block = output.replace('\r', '')[frames[0].end():frames[1].start()].strip('\n')
    if not block.startswith(': '):
        raise ValueError('Unrecognized player response. Inspect the console.')
    lines = block[2:].splitlines()
    if not lines:
        return None
    count = 0 if lines[-1] == 'No players connected.' else None
    match = re.fullmatch(r'([0-9]+) players? connected\.', lines[-1])
    if match:
        count = int(match[1])
    if count is None or count > 255 or len(lines) != count + 1:
        raise ValueError('Player output was incomplete or mixed with other console output. Refresh to try again.')
    players = []
    for line in lines[:-1]:
        match = re.fullmatch(r'(.+) \(([^\r\n]+)\)', line)
        if not match:
            raise ValueError('Unrecognized player entry. Refresh to try again.')
        name, address = match.groups()
        line_text(name, 100)
        players.append({'name': name, 'address': address, 'identifier': identifier(address)})
    for player in players:
        player['can_moderate'] = sum(p['name'].casefold() == player['name'].casefold() for p in players) == 1
    return players


def deliver(command):
    try:
        result = subprocess.run(['inject', command], capture_output=True, text=True, timeout=7)
    except subprocess.TimeoutExpired:
        raise ValueError('Command delivery is uncertain. Inspect the console before retrying.') from None
    if result.returncode:
        raise ValueError('Command could not be delivered. Check game health.')


def session(log):
    return ((settings.RUNTIME / 'server.pid').read_text(), log.stat().st_ino,
            log.with_name(log.name + '.first').read_text())


def snapshot(log, force=False):
    global CACHE, CACHE_AT
    running = settings.read_json(settings.RUNTIME / 'admin-effective.json', settings.effective())
    if running.get('TMOD_LANGUAGE', 'en-US') != 'en-US':
        raise ValueError('Player management currently requires English console output (TMOD_LANGUAGE=en-US). Use the console for this server language.')
    current = session(log)
    if not force and CACHE and CACHE.get('_session') == current and time.monotonic() - CACHE_AT < 8:
        return CACHE
    CACHE = None
    with log.open('rb') as stream:
        stream.seek(0, 2)
        for command in ('version', 'playing', 'version'):
            deliver(command)
        deadline = time.monotonic() + 5
        output = b''
        while time.monotonic() < deadline:
            output += stream.read(65537 - len(output))
            if len(output) > 65536:
                raise ValueError('Console output exceeded the player-query limit. Try again when output is quieter.')
            try:
                decoded = output.decode('utf-8', errors='strict')
            except UnicodeDecodeError as error:
                if error.reason != 'unexpected end of data':
                    raise ValueError('Player output is not valid UTF-8. Use the console.') from error
                time.sleep(.1)
                continue
            players = parse_roster(decoded)
            if players is not None:
                if session(log) != current:
                    raise ValueError('The game restarted during the query. Refresh the player list.')
                stamp = admin_metrics.timestamp()
                for player in players:
                    player['key'] = hashlib.sha256(json.dumps([current, player['name'], player['address']]).encode()).hexdigest()
                CACHE = {'players': players, 'updated': stamp, '_session': current}
                CACHE_AT = time.monotonic()
                try:
                    import admin_player_history
                    admin_player_history.observe_roster(players)
                except (OSError, ValueError, sqlite3.Error) as error:
                    print('[ADMIN] Could not retain player connection identifiers: ' + str(error), flush=True)
                return CACHE
            time.sleep(.1)
    raise ValueError('The game did not return a complete player list. Refresh or inspect the console; player count is unknown.')


def audit(action, target, detail):
    path = settings.DATA / '.tmod-control/player-activity.json'
    previous = settings.read_json(path, [])
    rows = ([{'time': admin_metrics.timestamp(), 'action': action,
              'target': target, 'detail': detail}] + previous)[:50]
    while len(json.dumps(rows).encode()) > 60000:
        rows.pop()
    settings.atomic_json(path, rows)


def activity():
    rows = settings.read_json(settings.DATA / '.tmod-control/player-activity.json', [])
    for row in rows:
        if row.get('action') in ('kick', 'ban') and row.get('detail') == 'Command delivered; game outcome is not yet confirmed.':
            row['detail'] = row['action'].capitalize() + ' command sent.'
    return rows


def ban_path():
    custom = os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1')
    if custom:
        raise ValueError('Dashboard bans require the generated configuration with its persistent ban list. Use the console for a custom configuration.')
    return settings.DATA / 'tModLoader/banlist.txt'


def ban_entries():
    path = ban_path()
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Linked ban files cannot be managed here.')
    if not path.exists():
        return set()
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('The ban file is unsupported or exceeds 1 MiB; inspect it before editing.')
    return set(path.read_text(encoding='utf-8-sig').splitlines())


def ban_recorded(payload):
    """Append one reviewed native identifier; never send an offline name command."""
    import admin_player_history
    if payload.get('confirm') is not True:
        raise ValueError('Review and confirm the recorded connection before banning.')
    target = admin_player_history.ban_target(payload.get('key'))
    value = target['identifier']
    # Revalidate stored data too; no newlines, names, or client-provided targets.
    normalized = identifier(value if target['kind'] == 'steam' else '[' + value + ']:1')
    if normalized != value:
        raise ValueError('The saved ban identifier is invalid.')
    entries = ban_entries()
    if value in entries:
        return {'detail': 'This identifier is already in the persistent ban list.'}
    path = ban_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError('Ban file changed; refresh and review it again.')
        existing = os.read(descriptor, 1024 * 1024 + 1)
        if value not in existing.decode('utf-8-sig').splitlines():
            # Append preserves concurrent native bans instead of replacing the file.
            addition = (b'\n' if existing and not existing.endswith(b'\n') else b'') + (value + '\n').encode()
            if len(existing) + len(addition) > 1024 * 1024:
                raise ValueError('The ban file would exceed 1 MiB; inspect it before editing.')
            if os.write(descriptor, addition) != len(addition):
                raise OSError('Ban write was incomplete; inspect the ban list before retrying.')
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if value not in ban_entries():
        raise ValueError('Ban persistence could not be verified. Inspect the ban list.')
    detail = 'Ban saved for ' + value + '. It applies to future connections using this identifier; it does not disconnect an existing session.'
    if target['kind'] == 'ip':
        detail += ' This is an IP ban, not an account ban; shared or changed IP addresses affect its scope.'
    audit('historical ban', target['name'], detail)
    return {'detail': detail}


def unban_recorded(payload):
    """Clear exact identifier lines in place, preserving concurrent native appends."""
    import admin_player_history
    if payload.get('confirm') is not True:
        raise ValueError('Review and confirm the recorded connection before unbanning.')
    target = admin_player_history.ban_target(payload.get('key'))
    value = target['identifier']
    if identifier(value if target['kind'] == 'steam' else '[' + value + ']:1') != value:
        raise ValueError('The saved ban identifier is invalid.')
    if value not in ban_entries():
        return {'detail': 'This identifier is not in the persistent ban list.'}
    descriptor = os.open(ban_path(), os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError('Ban file changed; refresh and review it again.')
        raw = os.read(descriptor, 1024 * 1024 + 1)
        offset = 0
        for line in raw.splitlines(keepends=True):
            prefix = 3 if offset == 0 and line.startswith(b'\xef\xbb\xbf') else 0
            content = line[prefix:].rstrip(b'\r\n')
            if content.decode('utf-8') == value:
                # Equal-length comments avoid truncating or replacing native bans
                # appended by the game while this operation is in progress.
                os.lseek(descriptor, offset + prefix, os.SEEK_SET)
                if os.read(descriptor, len(content)) != content:
                    raise ValueError('Ban file changed; refresh and review it again.')
                os.lseek(descriptor, offset + prefix, os.SEEK_SET)
                replacement = b'//' + b' ' * (len(content) - 2)
                if os.write(descriptor, replacement) != len(content):
                    raise OSError('Unban write was incomplete; inspect the ban list.')
            offset += len(line)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if value in ban_entries():
        raise ValueError('Unban persistence could not be verified. Refresh the ban list.')
    detail = 'Ban removed for ' + value + '. Other banned addresses remain blocked.'
    audit('unban', target['name'], detail)
    return {'detail': detail}


def moderate(log, payload):
    action = payload.get('action')
    if action not in ('kick', 'ban') or payload.get('confirm') is not True:
        raise ValueError('Choose Kick or Ban and explicitly confirm the action.')
    roster = snapshot(log, force=True)
    matches = [p for p in roster['players'] if p['key'] == payload.get('key')]
    if len(matches) != 1 or not matches[0]['can_moderate']:
        raise ValueError('Player left, reconnected, or has an ambiguous name. Refresh and review the player before acting.')
    player = matches[0]
    if action == 'ban':
        ban_path()
    deliver(action + ' ' + player['name'])
    audit(action, player['name'], action.capitalize() + ' command sent.')
    # A fresh roster confirms departure; ban persistence is checked separately.
    after = snapshot(log, force=True)
    left = all(p['key'] != player['key'] for p in after['players'])
    banned = False
    if action == 'ban':
        path = ban_path()
        if path.exists() and path.stat().st_size <= 1024 * 1024:
            banned = player['identifier'] in path.read_text().splitlines()
    detail = ('Player is no longer connected.' if left else 'Command delivered; player is still listed. Refresh to check departure.')
    if action == 'ban':
        detail += ' Ban recorded in persistent storage.' if banned else ' Ban persistence was not confirmed; inspect the console.'
    audit(action + ' result', player['name'], detail)
    return {'detail': detail}
