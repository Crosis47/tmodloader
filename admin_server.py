"""Private, token-authenticated WSGI administration API and static interface."""
import hashlib
import hmac
import secrets
import codecs
import datetime
import re
import admin_auth
import admin_access
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.parse
import uuid

import admin_metrics
import admin_settings as settings
import admin_workshop as workshop
import admin_schema
import admin_recovery
import admin_players
import admin_worlds
import admin_modconfigs
import admin_journey
import admin_profiles
import admin_playthroughs
import admin_updates

STATIC = Path(__file__).parent / 'web'
OPERATION = threading.Lock()
STATE_LOCK = threading.Lock()
JOB = {'state': 'idle'}
TOKEN_HASH = ''
SETUP_CODE = ''
SETUP_LOCK = threading.Lock()
SETUP_NEXT = 0.0

def mark_auth_ready():
    (settings.RUNTIME / 'admin-auth-ready').write_text('ready')

def setup_request(method, payload):
    global TOKEN_HASH, SETUP_CODE, SETUP_NEXT
    with SETUP_LOCK:
        if TOKEN_HASH or not SETUP_CODE:
            raise PermissionError('Setup is unavailable.')
        if method != 'POST':
            raise PermissionError('Setup requires POST.')
        if time.monotonic() < SETUP_NEXT:
            raise PermissionError('Wait a moment before trying setup again.')
        SETUP_NEXT = time.monotonic() + 1
        code = payload.get('code', '')
        if not isinstance(code, str) or not hmac.compare_digest(code.encode(), SETUP_CODE.encode()):
            raise PermissionError('Invalid setup code. Read the container logs.')
        token = payload.get('token', '')
        if not isinstance(token, str):
            raise ValueError('Expected an admin token.')
        admin_auth.validate_token(token)
        if token != payload.get('confirm'):
            raise ValueError('Tokens do not match.')
        admin_auth.save_token(admin_auth.token_path(), token)
        TOKEN_HASH = admin_auth.read_hash(admin_auth.token_path())
        SETUP_CODE = ''
        mark_auth_ready()
        return {'ready': True}

CONSOLE_LOG = settings.DATA / 'tModLoader/Logs/container-console.log'


def running_mods(healthy):
    if not healthy:
        return {'available': False, 'mods': [], 'detail': 'Server is not ready; loaded mods cannot be confirmed.'}
    path = CONSOLE_LOG.with_name('server.log')
    try:
        with path.open('rb') as stream:
            content = stream.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            return {'available': False, 'mods': [], 'detail': 'Server log exceeds the inspection limit; check the console for loaded mods.'}
        mods, completed = {}, False
        for line in content.decode('utf-8', errors='replace').splitlines():
            if '[tML]: Finding Mods...' in line or '[tML]: Unloading Mods...' in line:
                mods, completed = {}, False
            match = re.search(r'\[tML\]: Finalizing Content: ([\w.-]+) \((.*)\) v(\S+)$', line)
            if match and match[1] != 'ModLoader':
                mods[match[1]] = {'name': match[2], 'version': match[3], 'internal_name': match[1]}
            if '[tML]: Mod Load Completed' in line:
                completed = True
        return {'available': completed, 'mods': sorted(mods.values(), key=lambda mod: mod['name'].casefold()) if completed else [],
                'detail': 'Loaded mods reported by the game; tModLoader itself is excluded.' if completed else 'No completed mod-loading record found in the server log.'}
    except OSError:
        return {'available': False, 'mods': [], 'detail': 'Server log is unavailable; loaded mods cannot be confirmed.'}


def console_sources():
    paths = [('current', CONSOLE_LOG), ('previous', CONSOLE_LOG.with_name('container-console.previous.log'))]
    directory = CONSOLE_LOG.parent / 'console-history'
    if not directory.is_symlink():
        paths += [(path.name, path) for path in directory.glob('run-*.log')
                  if re.fullmatch(r'run-\d{8}T\d{6}Z-[A-Za-z0-9]+\.log', path.name)]
    result = []
    for identity, path in paths:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            first = None
            marker = path.with_name(path.name + '.first')
            try:
                if not marker.is_symlink():
                    with marker.open() as stream:
                        parsed = datetime.datetime.fromisoformat(stream.read(128).strip())
                    if parsed.tzinfo is not None and parsed.timestamp() <= info.st_mtime:
                        first = parsed.isoformat()
            except (OSError, ValueError):
                pass
            result.append({'id': identity, 'first': first, 'updated': datetime.datetime.fromtimestamp(info.st_mtime, datetime.timezone.utc).isoformat(), 'bytes': info.st_size})
        except FileNotFoundError:
            continue  # A run may rotate while listing.
    return {'runs': sorted(result, key=lambda item: item['updated'], reverse=True)}


def console_output(query=None):
    query = query or {}
    history = query.get('mode', ['live'])[0] == 'history'
    source = query.get('source', ['current'])[0]
    if source in ('current', 'previous'):
        log_path = CONSOLE_LOG if source == 'current' else CONSOLE_LOG.with_name('container-console.previous.log')
    elif re.fullmatch(r'run-\d{8}T\d{6}Z-[A-Za-z0-9]+\.log', source):
        log_path = CONSOLE_LOG.parent / 'console-history' / source
    else:
        raise ValueError('Unknown console log.')
    if log_path.is_symlink() or log_path.parent.is_symlink():
        raise ValueError('Unknown console log.')
    offset = int(query.get('offset', ['0'])[0])
    if offset < 0:
        raise ValueError('History offset must be non-negative.')
    try:
        with log_path.open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            if history:
                identity = str(os.fstat(stream.fileno()).st_ino)
                if query.get('identity', [identity])[0] != identity:
                    raise ValueError('Log rotated. Return to the beginning or select the previous run.')
                if offset > size:
                    raise ValueError('Log was truncated. Return to the beginning of history.')
                stream.seek(offset)
                raw = stream.read(65536)
                decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
                content = decoder.decode(raw, final=offset + len(raw) >= size)
                next_offset = offset + len(raw) - len(decoder.getstate()[0])
                return {'output': content, 'available': True, 'offset': offset,
                        'next_offset': next_offset, 'total_bytes': size, 'done': next_offset >= size, 'identity': identity}
            stream.seek(max(0, size - 65536))
            content = stream.read(65536).decode('utf-8', errors='replace')
        lines = content.splitlines()
        if size > 65536:
            lines = lines[1:]  # Drop a possibly truncated first line.
        return {'output': '\n'.join(lines[-200:]), 'available': True, 'line_limit': 200}
    except FileNotFoundError:
        return {'output': 'No console output yet. The server may still be starting.', 'available': False, 'line_limit': 200}


def operation_busy():
    """Include CLI backups as well as jobs started by the administration API.

    Callers that mutate state must hold STATE_LOCK through their operation.
    """
    return (JOB.get('state') == 'running' or settings.read_json(admin_metrics.STATE).get('state') == 'running'
            or admin_updates.read(admin_updates.ROOT / 'status.json').get('state') in admin_updates.BUSY)


def send_console(payload):
    command = payload.get('command')
    if not isinstance(command, str) or not command.strip() or len(command) > 4000 or any(ord(c) < 32 or ord(c) == 127 for c in command):
        raise ValueError('Enter one server command, at most 4000 characters, without control characters.')
    command = command.strip()
    if command.split()[0].lower() in ('exit', 'exit-nosave') and payload.get('confirm_stop') is not True:
        raise ValueError('Stopping the server requires explicit confirmation.')
    with STATE_LOCK:
        if operation_busy():
            raise ValueError('Wait for the current backup or administration operation before sending commands.')
        if not health():
            raise ValueError('The game server is not ready to receive commands.')
        try:
            result = subprocess.run(['inject', command], capture_output=True, text=True, timeout=7)
        except subprocess.TimeoutExpired:
            raise ValueError('Command delivery was not confirmed. Check output before retrying.') from None
        if result.returncode:
            raise ValueError('Command delivery failed. Check server state before retrying.')
    return {'sent': True, 'detail': 'Sent to the game. Output appears asynchronously; this does not confirm command success.'}


def revision(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def configuration():
    running = settings.read_json(settings.RUNTIME / 'admin-effective.json', settings.effective())
    staged = settings.clean_mod_selection({**running, **settings.read_json(settings.PENDING, running)})
    changes = [{'key': key, 'label': admin_schema.FIELDS.get(key, {}).get('label', key),
                'running': running.get(key), 'staged': value}
               for key, value in sorted(staged.items()) if value != running.get(key)]
    return {'mode': 'web' if settings.web_mode() else 'env', 'running': running,
            'staged': staged, 'revision': revision(staged),
            'pending': settings.PENDING.exists() and bool(changes),
            'changes': changes if settings.PENDING.exists() else [],
            'draft_exists': settings.PENDING.exists(),
            'ranges': settings.RANGES, 'choices': settings.CHOICES,
            'groups': [{'id': identity, 'title': title, 'description': description} for identity, title, description in admin_schema.GROUPS],
            'fields': admin_schema.FIELDS,
            'compose_only': {'TMOD_PORT': os.environ.get('TMOD_PORT', '7777'),
                             'TMOD_USECONFIGFILE': os.environ.get('TMOD_USECONFIGFILE', 'No'),
                             'password': 'Hidden; managed through Compose or a secret file'},
            'workshop_search': workshop.key_available()}


def health():
    try:
        return subprocess.run(['healthcheck'], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def job_runner(kind, archive=None, checksum=None):
    global JOB
    try:
        if kind in ('backup', 'verify', 'preview', 'inspect', 'prepare'):
            command = ['tmod-backup', '_' + kind if kind in ('preview', 'inspect', 'prepare') else kind]
            if archive:
                command += ['--archive', str(archive)]
            if kind == 'prepare':
                command += ['--confirm', '--sha256', checksum]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise ValueError(result.stderr[-2000:] or 'Operation failed; inspect container logs and backup status.')
            if kind in ('preview', 'inspect', 'prepare'):
                JOB = {**JOB, kind: json.loads(result.stdout)}
        else:
            request_id = uuid.uuid4().hex
            if kind == 'apply':
                notice_path = settings.PENDING.with_name('pending-removed.json')
                names = settings.read_json(notice_path).get('names', [])
                settings.atomic_json(settings.RUNTIME / 'admin-removed', {'id': request_id, 'names': names})
                settings.atomic_json(notice_path, {'names': []})
            settings.atomic_json(settings.RUNTIME / 'admin-request', {'id': request_id, 'kind': kind,
                                 'archive': str(archive) if archive else None, 'sha256': checksum})
            while True:
                removals = settings.read_json(settings.RUNTIME / 'admin-removed')
                if removals.get('id') == request_id:
                    JOB = {**JOB, 'removed_client_mods': removals.get('names', [])}
                progress = settings.read_json(settings.RUNTIME / 'admin-progress')
                if progress.get('id') == request_id:
                    JOB = {**JOB, 'stage': progress.get('stage'), 'detail': progress.get('detail')}
                result = settings.read_json(settings.RUNTIME / 'admin-result')
                if result.get('id') == request_id:
                    removals = settings.read_json(settings.RUNTIME / 'admin-removed')
                    if removals.get('id') == request_id:
                        JOB = {**JOB, 'removed_client_mods': removals.get('names', [])}
                    if result.get('status') != 0:
                        raise ValueError(result.get('detail') or 'Operation failed; inspect container logs. Server may be stopped.')
                    break
                pid_file = settings.RUNTIME / 'supervisor.pid'
                if not pid_file.exists():
                    raise ValueError('Supervisor stopped before completing the operation.')
                os.kill(int(pid_file.read_text()), 0)
                time.sleep(1)
        detail = 'Operation completed.'
        if kind in ('apply', 'restore', 'retry', 'runtime-update'):
            detail = 'Game server is healthy.'
            if kind == 'runtime-update':
                detail = result.get('detail') or detail
        elif kind == 'preview':
            detail = 'Archive verified; review the preview before restoring.'
        elif kind == 'inspect':
            detail = 'Archive verified. Expand its row to review contents and compatibility.'
        elif kind == 'prepare':
            detail = 'Prepared copy: ' + JOB['prepare']['archive'] + '. Original preserved; select the copy to preview a restore.'
        JOB = {**JOB, 'state': 'success', 'detail': detail, 'finished': admin_metrics.timestamp()}
    except Exception as error:
        JOB = {**JOB, 'state': 'failed', 'detail': str(error), 'finished': admin_metrics.timestamp()}
    finally:
        try:
            if kind in ('restore', 'retry'):
                admin_recovery.record(JOB)
        finally:
            OPERATION.release()


def start_job(kind, archive=None, checksum=None):
    global JOB
    if not OPERATION.acquire(blocking=False):
        raise ValueError('Another administration operation is running.')
    JOB = {'state': 'running', 'kind': kind, 'archive': archive.name if archive else None, 'stage': 'queued', 'detail': 'Checking archive.' if kind in ('inspect', 'preview', 'prepare', 'verify') else 'Waiting for the supervisor.', 'started': admin_metrics.timestamp()}
    if kind in ('restore', 'retry'):
        try:
            admin_recovery.record(JOB)
        except Exception:
            OPERATION.release()
            raise
    threading.Thread(target=job_runner, args=(kind, archive, checksum), daemon=True).start()
    return JOB


def playthroughs_request(method, payload):
    with STATE_LOCK:
        current = configuration()
        busy = operation_busy()
        if method == 'POST':
            if busy:
                raise ValueError('Wait for the current operation before changing playthroughs.')
            admin_playthroughs.change(payload, current)
            current = configuration()
        return {**admin_playthroughs.catalog(), 'revision': current['revision'],
                'running': admin_playthroughs.selection(current['running']),
                'staged': admin_playthroughs.selection(current['staged']),
                'worlds': admin_worlds.inventory(current['running'])['worlds'], 'editable': admin_playthroughs.editable(), 'pending': current['pending'], 'busy': busy}


def profiles_request(method, payload):
    with STATE_LOCK:
        current = configuration()
        busy = operation_busy()
        if method == 'POST':
            if busy:
                raise ValueError('Wait for the current operation before changing profiles.')
            admin_profiles.change(payload, current)
            current = configuration()
        return {**admin_profiles.catalog(), 'revision': current['revision'],
                'running': current['running'].get('TMOD_MODS', ''),
                'staged': current['staged'].get('TMOD_MODS', ''),
                'editable': settings.web_mode(), 'pending': current['pending'], 'busy': busy}


def journey_request(method, query, payload):
    with STATE_LOCK:
        name = query.get('name', [None])[0] if method == 'GET' else payload.get('name')
        if name is not None:
            admin_worlds.check('switch', name)
            metadata = admin_worlds.read_metadata(admin_worlds.world_path(name))
            if not metadata.get('available') or metadata.get('difficulty') != 'Journey':
                raise ValueError('Journey permissions are available only for confirmed Journey worlds.')
        current = configuration()
        if method == 'POST':
            if not settings.web_mode() or os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1'):
                raise ValueError('Enable web-managed generated configuration to edit Journey permissions.')
            if operation_busy():
                raise ValueError('Wait for the current operation before changing Journey permissions.')
            if payload.get('settings_revision') != current['revision']:
                raise ValueError('Settings changed. Close and reopen this dialog before saving.')
            admin_journey.save(payload)
            selected = current['staged'].get('TMOD_WORLDNAME')
            selected_metadata = admin_worlds.read_metadata(admin_worlds.world_path(selected)) if selected else {}
            intent = settings.read_json(settings.PENDING.with_name('pending-world.json'))
            selected_is_journey = selected_metadata.get('difficulty') == 'Journey' or (
                intent.get('action') == 'create' and intent.get('name') == selected and
                current['staged'].get('TMOD_DIFFICULTY') == '3')
            if selected_is_journey and (name is None or name == selected):
                values = {**current['staged'], **admin_journey.effective(selected)}
                if values != current['staged']:
                    settings.atomic_json(settings.PENDING, values)
            current = configuration()
        return {**admin_journey.state(name), 'settings_revision': current['revision'],
                'running': admin_journey.permissions(current['running']),
                'running_world': current['running'].get('TMOD_WORLDNAME'),
                'editable': settings.web_mode() and os.environ.get('TMOD_USECONFIGFILE', 'No').lower() not in ('yes', 'true', '1')}


def worlds_status():
    config = configuration()
    healthy = health()
    return {**admin_worlds.inventory(config['running'], healthy=healthy), 'healthy': healthy,
            'busy': operation_busy(),
            'revision': config['revision'], 'staged_name': config['staged'].get('TMOD_WORLDNAME'),
            'pending': config['pending']}


def stage_world(payload):
    with STATE_LOCK:
        if not settings.web_mode() or os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1'):
            raise ValueError('Enable web-managed generated configuration to manage worlds here.')
        if operation_busy():
            raise ValueError('Wait for the current operation before choosing a world.')
        current = configuration()
        if payload.get('revision') != current['revision']:
            raise ValueError('Settings changed. Refresh and review the latest draft.')
        admin_worlds.stage(payload, current)
        return configuration()


def players_status():
    with STATE_LOCK:
        result = {'available': False, 'players': [], 'updated': None,
                  'activity': admin_players.activity(), 'can_ban': False}
        try:
            players_ready()
            roster = admin_players.snapshot(CONSOLE_LOG)
            result.update({k: v for k, v in roster.items() if not k.startswith('_')})
            result.update(available=True, detail='Fresh native server query; refreshes every 10 seconds while this page is open.')
            try:
                admin_players.ban_path()
                result['can_ban'] = True
            except ValueError:
                pass
        except (ValueError, OSError) as error:
            result['detail'] = str(error)
        return result


def player_command(path, payload):
    with STATE_LOCK:
        players_ready()
        if path.endswith('/moderate'):
            return admin_players.moderate(CONSOLE_LOG, payload)
        if payload.get('confirm') is not True:
            raise ValueError('Confirm the announcement before sending.')
        message = admin_players.line_text(payload.get('message'))
        if not message.strip():
            raise ValueError('Announcement text cannot be blank.')
        admin_players.deliver('say ' + message)
        detail = 'Announcement command delivered. Client receipt cannot be confirmed by the server console.'
        admin_players.audit('announcement', message, detail)
        return {'detail': detail}


def recovery_request(path, payload):
    kind = path.rsplit('/', 1)[-1]
    with STATE_LOCK:
        if settings.read_json(admin_metrics.STATE).get('state') == 'running':
            raise ValueError('Wait for the current backup to finish.')
        if kind not in ('preview', 'inspect') and payload.get('confirm') is not True:
            raise ValueError('Explicit confirmation is required.')
        if kind not in ('preview', 'inspect') and admin_recovery.status()['interrupted']:
            raise ValueError('An interrupted restore requires manual recovery. Read the Recovery page guidance.')
        checksum = payload.get('sha256')
        if kind in ('restore', 'prepare') and (not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum)):
            raise ValueError('Preview the archive before restoring.')
        archive = None if kind == 'retry' else admin_recovery.archive_path(payload.get('archive'))
        return start_job(kind, archive, checksum)


def server_status():
    healthy = health()
    return {'healthy': healthy, 'mods': running_mods(healthy), 'backups': admin_metrics.inventory(), 'job': JOB,
            'updates': admin_updates.status(),
            'version': Path('/terraria-server/VERSION').read_text().strip()
            if Path('/terraria-server/VERSION').exists() else 'development'}


def save_settings(payload):
    if not settings.web_mode():
        raise ValueError('Enable TMOD_CONFIG_SOURCE=web in Compose to edit settings.')
    with STATE_LOCK:
        if operation_busy():
            raise ValueError('Wait for the current operation before changing settings.')
        current = configuration()
        if payload.get('revision') != current['revision']:
            raise ValueError('Settings changed in another session. Reload before saving.')
        removed = []
        values = settings.clean_mod_selection(settings.validate(payload.get('settings')), removed)
        settings.atomic_json(settings.PENDING, {**current['staged'], **values})
        settings.record_pending_removals(removed)
    return configuration()


def operation_request(path, payload):
    if payload.get('confirm') is not True:
        raise ValueError('Explicit confirmation is required.')
    kind = path.rsplit('/', 1)[-1]
    with STATE_LOCK:
        if kind == 'apply' and admin_recovery.status()['interrupted']:
            raise ValueError('An interrupted restore must be recovered before applying settings.')
        if kind == 'apply' and (not settings.web_mode() or not settings.PENDING.exists()):
            raise ValueError('No staged web-managed settings to apply.')
        if kind == 'apply' and payload.get('revision') != configuration()['revision']:
            raise ValueError('The staged draft changed. Reload and review it before applying.')
        if kind == 'apply':
            admin_worlds.validate_pending()
        archive = None
        if kind == 'verify':
            name = payload.get('archive', '')
            if not isinstance(name, str) or not name.startswith('tmod-backup-') or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Invalid archive name.')
            archive = admin_metrics.DEST / name
            if archive.is_symlink() or not archive.is_dir():
                raise ValueError('Archive not found.')
        return start_job(kind, archive)


def api(method, path, query, payload):
    """Dispatch authenticated requests; feature handlers own validation and locking."""
    if (method == 'POST' and path != '/api/updates/check'
            and admin_updates.read(admin_updates.ROOT / 'status.json').get('state') in admin_updates.BUSY):
        raise ValueError('Wait for startup update preparation to finish before changing server data.')
    if path == '/api/updates' and method == 'GET':
        return admin_updates.status()
    if path == '/api/updates/log' and method == 'GET':
        return admin_updates.diagnostics()
    if path == '/api/updates/announcements' and method == 'POST':
        if not isinstance(payload.get('enabled'), bool):
            raise ValueError('Choose whether update announcements are enabled.')
        with STATE_LOCK:
            settings.atomic_json(admin_updates.ROOT / 'announcements.json', {'enabled': payload['enabled']})
        return admin_updates.status(refresh=False)
    if path == '/api/updates/check' and method == 'POST':
        admin_updates.request_check(force=True)
        return admin_updates.status(refresh=False)
    if path == '/api/updates/restart' and method == 'POST':
        with STATE_LOCK:
            if operation_busy():
                raise ValueError('Wait for the current operation before restarting the game.')
            if payload.get('confirm') is not True:
                raise ValueError('Explicit confirmation is required.')
            if admin_recovery.status()['interrupted']:
                raise ValueError('Recover the interrupted archive restore before restarting.')
            return start_job('runtime-update')
    if path == '/api/updates/delete-checkpoint' and method == 'POST':
        with STATE_LOCK:
            if operation_busy():
                raise ValueError('Wait for the current operation before deleting recovery data.')
            if payload.get('confirm') is not True:
                raise ValueError('Explicit confirmation is required.')
            if not health():
                raise ValueError('Verify the game is healthy before deleting its recovery checkpoint.')
            import runtime_updates
            runtime_updates.delete_checkpoint(payload.get('checkpoint'))
            return admin_updates.status(refresh=False)
    if path in ('/api/updates/rollback', '/api/updates/cancel') and method == 'POST':
        with STATE_LOCK:
            if operation_busy():
                raise ValueError('Wait for the current operation before changing update recovery.')
            if payload.get('confirm') is not True:
                raise ValueError('Explicit confirmation is required.')
            if path.endswith('/rollback'):
                if not admin_updates.status(refresh=False)['rollback_available']:
                    raise ValueError('No runtime update checkpoint is available.')
                settings.atomic_json(admin_updates.ROOT / 'rollback-request.json', {'requested': admin_updates.stamp()})
            else:
                (admin_updates.ROOT / 'rollback-request.json').unlink(missing_ok=True)
            return admin_updates.status(refresh=False)
    if path == '/api/mod-configs/validate' and method == 'POST':
        admin_modconfigs.path_for(payload.get('name'))
        return admin_modconfigs.validate_content(payload['name'], payload.get('content'))
    if path == '/api/mod-configs' and method in ('GET', 'POST'):
        with STATE_LOCK:
            if method == 'GET':
                return admin_modconfigs.read(query['name'][0]) if query.get('name') else admin_modconfigs.inventory()
            if operation_busy():
                raise ValueError('Wait for the current server operation before saving mod configuration.')
            return admin_modconfigs.save(payload)
    if method == 'POST' and path in ('/api/settings/discard', '/api/worlds/delete'):
        with STATE_LOCK:
            if operation_busy():
                raise ValueError('Wait for the current server operation.')
            current = configuration()
            if payload.get('revision') != current['revision']:
                raise ValueError('Settings changed. Refresh and review again.')
            if path == '/api/settings/discard':
                for name in ('pending.json', 'pending-world.json', 'pending-removed.json'):
                    settings.PENDING.with_name(name).unlink(missing_ok=True)
                return configuration()
            if payload.get('confirm') is not True:
                raise ValueError('Confirm world deletion.')
            admin_worlds.delete(payload.get('name'), current)
            return {'deleted': payload.get('name')}
    if path == '/api/playthroughs' and method in ('GET', 'POST'):
        return playthroughs_request(method, payload)
    if path == '/api/profiles' and method in ('GET', 'POST'):
        return profiles_request(method, payload)
    if path == '/api/worlds/journey' and method in ('GET', 'POST'):
        return journey_request(method, query, payload)
    if method == 'GET' and path == '/api/worlds':
        return worlds_status()
    if method == 'POST' and path == '/api/worlds/stage':
        return stage_world(payload)
    if path == '/api/players' and method == 'GET':
        return players_status()
    if path in ('/api/players/moderate', '/api/players/announce') and method == 'POST':
        return player_command(path, payload)
    if method == 'GET' and path == '/api/recovery':
        return admin_recovery.status()
    if method == 'POST' and path in ('/api/recovery/preview', '/api/recovery/restore', '/api/recovery/retry', '/api/recovery/inspect', '/api/recovery/prepare'):
        return recovery_request(path, payload)
    if method == 'GET' and path == '/api/console/runs':
        return console_sources()
    if method == 'GET' and path == '/api/console':
        return console_output(query)
    if method == 'POST' and path == '/api/console':
        return send_console(payload)
    if method == 'GET' and path == '/api/status':
        return server_status()
    if method == 'GET' and path == '/api/settings':
        return configuration()
    if method == 'GET' and path == '/api/workshop':
        return workshop.query(query.get('q', [''])[0], query.get('sort', ['popular'])[0],
                              int(query.get('page', ['1'])[0]), query.get('tag', [''])[0])
    if method == 'POST' and path == '/api/workshop/lookup':
        return workshop.lookup(str(payload.get('value', '')))
    if method == 'POST' and path == '/api/workshop/dependencies':
        return workshop.dependencies(str(payload.get('id', '')))
    if method == 'POST' and path == '/api/workshop/key':
        return workshop.save_key(payload.get('key'))
    if method == 'POST' and path == '/api/settings':
        return save_settings(payload)
    if method == 'POST' and path in ('/api/backup', '/api/apply', '/api/verify'):
        return operation_request(path, payload)
    raise LookupError('Endpoint not found.')


def players_ready():
    if operation_busy():
        raise ValueError('Player controls are paused during backup, restore or settings changes.')
    if not health():
        raise ValueError('Game is not ready. Player count is unknown until it is healthy.')
    running = settings.read_json(settings.RUNTIME / 'admin-effective.json', settings.effective())
    if running.get('TMOD_LANGUAGE', 'en-US') != 'en-US':
        raise ValueError('Player management requires TMOD_LANGUAGE=en-US. Use the console for this server language.')


def application(environ, start_response):
    status, content_type = '200 OK', 'application/json; charset=utf-8'
    headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
               ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
               ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://*.steamusercontent.com https://*.steamstatic.com https://*.akamaihd.net; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
    path, method = environ.get('PATH_INFO', '/'), environ['REQUEST_METHOD']
    try:
        admin_access.check_request(environ)
        if path.startswith('/api/'):
            supplied = environ.get('HTTP_AUTHORIZATION', '')
            if path != '/api/setup' and (not supplied.startswith('Bearer ') or not admin_auth.verify(TOKEN_HASH, supplied[7:])):
                raise PermissionError('Authentication required.')
            payload = {}
            if method == 'POST':
                length = int(environ.get('CONTENT_LENGTH') or '0')
                body_limit = 524288 if path in ('/api/mod-configs', '/api/mod-configs/validate') else 65536
                if not 0 < length <= body_limit or environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                    raise ValueError(f'Expected a JSON body of at most {body_limit // 1024} KiB.')
                payload = json.loads(environ['wsgi.input'].read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object.')
            with workshop.authenticated(supplied[7:] if path != '/api/setup' else ''):
                body = json.dumps(setup_request(method, payload) if path == '/api/setup' else api(method, path, urllib.parse.parse_qs(environ.get('QUERY_STRING', '')), payload)).encode()
        elif method == 'GET' and path in ('/', '/app.js', '/style.css', '/setup.js'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/setup.js': 'setup.js'}[path]
            content_type = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css', '/setup.js': 'text/javascript'}[path] + '; charset=utf-8'
            if path == '/' and not TOKEN_HASH:
                name = 'setup.html'
            body = (STATIC / name).read_bytes()
        else:
            raise LookupError('Not found.')
    except PermissionError as error:
        status, body = '403 Forbidden', json.dumps({'error': str(error)}).encode()
    except (ValueError, TypeError) as error:
        status, body = '400 Bad Request', json.dumps({'error': str(error)}).encode()
    except LookupError as error:
        status, body = '404 Not Found', json.dumps({'error': str(error)}).encode()
    except Exception:
        status, body = '500 Internal Server Error', b'{"error":"Operation unavailable; inspect container state and permissions."}'
    start_response(status, headers + [('Content-Type', content_type), ('Content-Length', str(len(body)))])
    return [body]


def update_announcement_worker():
    while True:
        try:
            with STATE_LOCK:
                if not operation_busy():
                    admin_updates.announce_available()
        except Exception as error:
            print('[ADMIN] Update announcement check failed: ' + str(error), flush=True)
        time.sleep(60)


def main():
    global TOKEN_HASH, SETUP_CODE
    previous = admin_recovery.status()['operation']
    if previous.get('state') == 'running':
        admin_recovery.record({**previous, 'state': 'interrupted', 'detail': 'Container restarted before recovery completion was recorded. Inspect game health and retained originals before retrying.'})
    if admin_auth.token_path().exists():
        TOKEN_HASH = admin_auth.read_hash(admin_auth.token_path())
    else:
        SETUP_CODE = secrets.token_urlsafe(32)
    admin_access.validate_config()
    if TOKEN_HASH:
        mark_auth_ready()
    else:
        print('[ADMIN] Game startup paused. Open the dashboard to create your admin token.', flush=True)
        print('[ADMIN] One-time setup code: ' + SETUP_CODE, flush=True)
    from waitress import serve
    threading.Thread(target=update_announcement_worker, daemon=True).start()
    print('[ADMIN] Open ' + (os.environ.get('TMOD_WEB_ORIGIN') or 'http://<server-IP>:<dashboard-port> (default 8080)') + ' in your browser.', flush=True)
    print('[ADMIN] Private administration interface listening on port 8080.', flush=True)
    serve(application, host='0.0.0.0', port=8080, threads=4, connection_limit=32,
          # admin_access validates raw headers against the unchanged socket peer.
          channel_timeout=30, max_request_body_size=524288, clear_untrusted_proxy_headers=False)


if __name__ == '__main__':
    admin_updates.CHECKS_ENABLED = True
    main()
