"""Durable character-name visits, recorded by the live console process.

World GUIDs survive file renames and switches. Server-observed connection
identifiers are retained separately for explicit, reviewed offline bans.
This database stays outside world backup/restore transactions so restoring an
older world does not erase the server's visit history.
"""
import contextlib
import hashlib
import hmac
import json
from pathlib import Path
import os
import re
import sqlite3
import sys
import threading
import time

import admin_metrics
import admin_settings as settings
from admin_world_metadata import read_metadata
from admin_world_time import process_identity

PAGE_SIZE = 50
EVENT = re.compile(r'^(.{1,100}) has (joined|left)\.$')
# tModLoader ModNet.Identifier supplies the endpoint and character together.
# Never correlate separate "is connecting" and "has joined" lines by timing.
NETWORK = re.compile(r'^\[[^\]\r\n]+\] \[[^\]\r\n]+/(?:INFO|WARN|ERROR)\] \[Network\]: '
                     r'\[[0-9]{1,3}\]\[(.+) \((.{1,100})\)\] .+$')


def database():
    return settings.DATA / '.tmod-control/player-history.sqlite3'


def session_path():
    return settings.RUNTIME / 'player-history-session.json'


@contextlib.contextmanager
def connection(write=False):
    path = database()
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Player history cannot use linked storage.')
    if write:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(str(path) if write else path.as_uri() + '?mode=ro', uri=not write, timeout=5)
    db.row_factory = sqlite3.Row
    db.create_function('casefold', 1, str.casefold, deterministic=True)
    try:
        if write:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS visits (
                    world TEXT NOT NULL, name TEXT NOT NULL,
                    first_joined TEXT NOT NULL, last_joined TEXT NOT NULL,
                    visits INTEGER NOT NULL, PRIMARY KEY(world, name));
                CREATE INDEX IF NOT EXISTS visits_recent ON visits(world, last_joined DESC, name);
                CREATE TABLE IF NOT EXISTS identities (
                    world TEXT NOT NULL, name TEXT NOT NULL, identifier TEXT NOT NULL,
                    key TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    PRIMARY KEY(world, name, identifier));
                CREATE INDEX IF NOT EXISTS identity_keys ON identities(key);
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, appearance TEXT NOT NULL);
            ''')
        with db:
            yield db
    finally:
        db.close()


def record(name, world=None):
    if not isinstance(name, str) or not name or len(name) > 100 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        return
    key = name
    stamp = admin_metrics.timestamp()
    with connection(write=True) as db:
        for identity in ['', world] if world else ['']:
            db.execute('''INSERT INTO visits VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(world, name) DO UPDATE SET
                last_joined=excluded.last_joined, visits=visits+1''', (identity, key, stamp, stamp))
    return key


def observe(name, address, world, source):
    """Retain only identifiers tied to an actual recorded visit, never a guess."""
    from admin_players import identifier, line_text
    line_text(name, 100)
    target = identifier(address)
    stored_name = name
    key = hashlib.sha256(json.dumps([stored_name, target]).encode()).hexdigest()
    kind = 'steam' if target.startswith('STEAM_') else 'ip'
    stamp = admin_metrics.timestamp()
    with connection(write=True) as db:
        for identity in ['', world] if world else ['']:
            if not db.execute('SELECT 1 FROM visits WHERE world=? AND name=?', (identity, stored_name)).fetchone():
                continue
            db.execute('''INSERT INTO identities VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(world, name, identifier) DO UPDATE SET
                last_seen=excluded.last_seen, source=excluded.source''',
                       (identity, stored_name, target, key, kind, source, stamp, stamp))


def observe_roster(players):
    world = current_world()['id']
    for player in players:
        observe(player['name'], player['address'], world, 'Native player query')


def ban_target(key):
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('Refresh player history and review the recorded ban target.')
    with connection() as db:
        row = db.execute('SELECT name, identifier, kind, last_seen FROM identities WHERE key=? '
                         'ORDER BY last_seen DESC LIMIT 1', (key,)).fetchone()
        result = dict(row) if row else None
        if result and db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone():
            character = db.execute('SELECT name FROM characters WHERE id=?', (result['name'],)).fetchone()
            if character:
                result['name'] = character['name']
    if not row:
        raise ValueError('That recorded connection is no longer available. Refresh player history.')
    return result


def read_session():
    path = session_path()
    if not path.exists():
        return {}
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Character session exceeds its size limit.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid character session state.')
    return value


def current_world():
    try:
        saved = read_session()
    except (OSError, ValueError):
        return {'id': None, 'name': None, 'detail': 'The loaded world could not be identified.'}
    if not saved.get('active') or not saved.get('owner_identity') or process_identity(saved.get('owner_pid')) != saved['owner_identity']:
        return {'id': None, 'name': None, 'detail': 'No world is currently loaded.'}
    return {key: saved.get(key) for key in ('id', 'name', 'detail')}


def page(db, world, offset, search):
    has_characters = db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone()
    source = 'visits v LEFT JOIN characters c ON c.id=v.name' if has_characters else 'visits v'
    display = 'coalesce(c.name, v.name)' if has_characters else 'v.name'
    # Fold older appearance-based records into their display name without deleting
    # their visits or the evidence supporting an existing ban target.
    grouped = ('SELECT ' + display + ' AS name, min(first_joined) AS first_joined, '
               'max(last_joined) AS last_joined, sum(visits) AS visits FROM ' + source +
               ' WHERE v.world=? GROUP BY ' + display)
    where = 'instr(casefold(name), casefold(?)) > 0'
    args = (world, search)
    count = db.execute('SELECT count(*) FROM (' + grouped + ') WHERE ' + where, args).fetchone()[0]
    offset = min(offset, max(0, (count - 1) // PAGE_SIZE * PAGE_SIZE))
    players = [dict(row) for row in db.execute('SELECT * FROM (' + grouped + ') WHERE ' + where +
               ' ORDER BY last_joined DESC, name LIMIT ? OFFSET ?', (*args, PAGE_SIZE, offset))]
    has_identities = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identities'").fetchone()
    for player in players:
        player['account_name'] = None
        player['identities'] = []
        if has_identities:
            identity_source = 'identities i LEFT JOIN characters c ON c.id=i.name' if has_characters else 'identities i'
            identity_name = 'coalesce(c.name, i.name)' if has_characters else 'i.name'
            targets = {}
            for row in db.execute('SELECT i.key, i.identifier, i.kind, i.source, i.first_seen, i.last_seen FROM ' +
                    identity_source + ' WHERE i.world=? AND ' + identity_name + '=? ORDER BY i.last_seen DESC, i.key',
                    (world, player['name'])):
                target = dict(row)
                if target['identifier'] not in targets:
                    targets[target['identifier']] = target
                else:
                    existing = targets[target['identifier']]
                    existing['first_seen'] = min(existing['first_seen'], target['first_seen'])
            player['identities'] = list(targets.values())
    return {'players': players, 'total': count, 'offset': offset, 'page_size': PAGE_SIZE}


def history(query=None):
    query = query or {}
    search = str(query.get('history_search', [''])[0])[:100]
    offsets = []
    for key in ('server_offset', 'world_offset'):
        try:
            offsets.append(max(0, min(1000000000, int(query.get(key, ['0'])[0]))))
        except (ValueError, TypeError):
            raise ValueError('Invalid player-history page.') from None
    empty = {'players': [], 'total': 0, 'offset': 0, 'page_size': PAGE_SIZE}
    result = {'server': dict(empty), 'world': dict(empty), 'current_world': current_world(), 'error': '',
              'can_ban': False, 'ban_detail': ''}
    try:
        if database().exists():
            with connection() as db:
                result['server'] = page(db, '', offsets[0], search)
                if result['current_world']['id']:
                    result['world'] = page(db, result['current_world']['id'], offsets[1], search)
    except (sqlite3.Error, OSError, ValueError) as error:
        result['error'] = 'Player history unavailable: ' + str(error)
    try:
        from admin_players import ban_entries
        banned = ban_entries()
        result['can_ban'] = not result['error']
        for scope in ('server', 'world'):
            for player in result[scope]['players']:
                for identity in player['identities']:
                    identity['banned'] = identity['identifier'] in banned
    except (OSError, ValueError) as error:
        result['ban_detail'] = str(error)
    return result


class VisitTracker:
    def __init__(self, config):
        self.config = Path(config)
        self.buffer = b''
        self.discard = False
        self.started = False
        self.online = set()
        self.seen = set()
        self.world = None
        self.saved = {}
        self.stop = threading.Event()
        self.thread = None
        self.log_offset = 0
        self.log_identity = None
        self.log_tail = b''
        self.pending_identities = {}
        self.bridge = False
        self.character_sessions = {}
        self.live = {}
        self.event_key = os.environ.get('TMOD_CHARACTER_EVENT_KEY')

    def start(self):
        if self.started:
            return
        values = {}
        for line in self.config.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip().lower()] = value.strip()
        self.english = values.get('language', os.environ.get('TMOD_LANGUAGE', 'en-US')) == 'en-US'
        path = Path(values['world']) if values.get('world') else None
        if path and not path.is_absolute():
            path = Path.cwd() / path
        metadata = read_metadata(path) if path else {}
        guid = metadata.get('world_guid') if metadata.get('available') else None
        self.world = guid if guid and guid != '00000000-0000-0000-0000-000000000000' else None
        detail = '' if self.world else 'The loaded world identity is unavailable; only server history is recorded.'
        if not self.english:
            detail = 'Player history requires English server output (TMOD_LANGUAGE=en-US).'
        if self.bridge:
            detail = '' if self.world else detail
        self.saved = {'id': self.world, 'name': metadata.get('title') or (path.stem if path else None),
                      'detail': detail, 'active': True, 'owner_pid': os.getpid(),
                      'owner_identity': process_identity(os.getpid())}
        settings.atomic_json(session_path(), self.saved)
        self.started = True
        self.thread = threading.Thread(target=self.watch_identities, daemon=True)
        self.thread.start()

    def read_identities(self):
        path = settings.DATA / 'tModLoader/Logs/server.log'
        if not path.is_file() or path.is_symlink():
            return
        with path.open('rb') as stream:
            stat = os.fstat(stream.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if self.log_identity != identity or stat.st_size < self.log_offset:
                self.log_offset, self.log_tail = 0, b''
                self.log_identity = identity
            stream.seek(self.log_offset)
            lines = (self.log_tail + stream.read(262144)).split(b'\n')
            self.log_offset = stream.tell()
            self.log_tail = lines.pop()[-4096:]
        for raw in lines:
            if len(raw) > 4096:
                continue
            match = NETWORK.fullmatch(raw.decode('utf-8', errors='replace').rstrip('\r'))
            if match:
                self.pending_identities[(match[2], match[1])] = time.monotonic()
        # Network logging can arrive before the console join announcement.
        # Retain only paired evidence, briefly and within a fixed memory bound.
        while len(self.pending_identities) > 1024:
            del self.pending_identities[next(iter(self.pending_identities))]
        for (name, address), observed in list(self.pending_identities.items()):
            if name in self.seen:
                try:
                    observe(name, address, self.world, 'Native network log')
                except ValueError:
                    pass  # Unsupported remote address formats are never ban targets.
                del self.pending_identities[(name, address)]
            elif time.monotonic() - observed > 30:
                del self.pending_identities[(name, address)]

    def watch_identities(self):
        while not self.stop.wait(1):
            try:
                self.read_identities()
            except (OSError, ValueError, sqlite3.Error) as error:
                print('[ADMIN] Player connection history unavailable: ' + str(error), file=sys.stderr, flush=True)

    def line(self, raw):
        text = raw.decode('utf-8', errors='strict').rstrip('\r')
        text = text.removeprefix(': ')
        if text.startswith('[CHARACTER] '):
            envelope = json.loads(text[len('[CHARACTER] '):])
            if not isinstance(envelope, dict):
                raise ValueError('Invalid character event.')
            if not self.event_key or not isinstance(envelope.get('key'), str) or not hmac.compare_digest(envelope['key'], self.event_key):
                return
            event = envelope.get('data')
            if not isinstance(event, dict):
                raise ValueError('Invalid character event payload.')
            if event.get('action') == 'ready':
                self.bridge = True
            elif self.started and self.bridge:
                self.character_event(event)
            return
        if text == 'Server started':
            self.start()
            return
        if not self.started or not self.english or self.bridge:
            return
        text = text.removeprefix(': ')
        # Console chat is prefixed with <sender>; do not interpret chat as joins.
        if re.match(r'^<[^>]+> ', text):
            return
        match = EVENT.fullmatch(text)
        if not match:
            return
        name, action = match.groups()
        if action == 'left':
            self.online.discard(name)
        elif name not in self.online:
            record(name, self.world)
            self.online.add(name)
            self.seen.add(name)

    def character_event(self, event):
        session = event.get('session')
        if not isinstance(session, str) or not re.fullmatch('[a-f0-9]{32}', session):
            raise ValueError('Invalid character session.')
        action = event.get('action')
        if action == 'left':
            self.character_sessions.pop(session, None)
            self.live.pop(session, None)
        elif action == 'joined' and session not in self.character_sessions:
            if len(self.character_sessions) >= 255:
                raise ValueError('Too many character sessions.')
            key = record(event.get('name'), self.world)
            if key:
                self.character_sessions[session] = key
                self.live[session] = {'name': event['name'], 'address': event.get('address')}
                try:
                    observe(event['name'], event['address'], self.world, 'Server character tracking')
                except ValueError:
                    pass
        settings.atomic_json(session_path(), {**self.saved, 'characters': list(self.live.values())})

    def feed(self, chunk):
        parts = (self.buffer + chunk).split(b'\n')
        self.buffer = parts.pop()
        for raw in parts:
            if not self.discard and len(raw) <= 4096:
                try:
                    self.line(raw)
                except (OSError, ValueError, sqlite3.Error) as error:
                    # The logging pipeline must keep draining even if tracking fails.
                    print('[ADMIN] Player history could not record output: ' + str(error), file=sys.stderr, flush=True)
            self.discard = False
        if len(self.buffer) > 4096:
            self.buffer = b''
            self.discard = True

    def finish(self):
        if self.started:
            self.stop.set()
            if self.thread:
                self.thread.join()
            try:
                self.read_identities()
            except (OSError, ValueError, sqlite3.Error) as error:
                print('[ADMIN] Final player connection history unavailable: ' + str(error), file=sys.stderr, flush=True)
            settings.atomic_json(session_path(), {**self.saved, 'active': False})
            self.started = False
