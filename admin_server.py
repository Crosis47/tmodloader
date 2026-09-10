"""Private, token-authenticated WSGI administration API and static interface."""
import hashlib
import codecs
import datetime
import re
import hmac
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

STATIC = Path(__file__).parent / 'web'
OPERATION = threading.Lock()
STATE_LOCK = threading.Lock()
JOB = {'state': 'idle'}
TOKEN = ''
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


def send_console(payload):
    command = payload.get('command')
    if not isinstance(command, str) or not command.strip() or len(command) > 4000 or any(ord(c) < 32 or ord(c) == 127 for c in command):
        raise ValueError('Enter one server command, at most 4000 characters, without control characters.')
    command = command.strip()
    if command.split()[0].lower() in ('exit', 'exit-nosave') and payload.get('confirm_stop') is not True:
        raise ValueError('Stopping the server requires explicit confirmation.')
    with STATE_LOCK:
        if JOB.get('state') == 'running' or settings.read_json(admin_metrics.STATE).get('state') == 'running':
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
    staged = settings.clean_mod_selection(settings.read_json(settings.PENDING, running))
    return {'mode': 'web' if settings.web_mode() else 'env', 'running': running,
            'staged': staged, 'revision': revision(staged), 'pending': settings.PENDING.exists(),
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


def job_runner(kind, archive=None):
    global JOB
    try:
        if kind in ('backup', 'verify'):
            command = ['tmod-backup', kind]
            if archive:
                command += ['--archive', str(archive)]
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                raise ValueError('Operation failed; inspect container logs and backup status.')
        else:
            request_id = uuid.uuid4().hex
            notice_path = settings.PENDING.with_name('pending-removed.json')
            names = settings.read_json(notice_path).get('names', [])
            settings.atomic_json(settings.RUNTIME / 'admin-removed', {'id': request_id, 'names': names})
            settings.atomic_json(notice_path, {'names': []})
            settings.atomic_json(settings.RUNTIME / 'admin-request', {'id': request_id})
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
                        raise ValueError('Apply failed; inspect container logs. Server may be stopped.')
                    break
                pid_file = settings.RUNTIME / 'supervisor.pid'
                if not pid_file.exists():
                    raise ValueError('Supervisor stopped before completing the operation.')
                os.kill(int(pid_file.read_text()), 0)
                time.sleep(1)
        JOB = {**JOB, 'state': 'success', 'detail': 'Settings applied; game server is healthy.' if kind == 'apply' else 'Operation completed.', 'finished': admin_metrics.timestamp()}
    except Exception as error:
        JOB = {**JOB, 'state': 'failed', 'detail': str(error), 'finished': admin_metrics.timestamp()}
    finally:
        OPERATION.release()


def start_job(kind, archive=None):
    global JOB
    if not OPERATION.acquire(blocking=False):
        raise ValueError('Another administration operation is running.')
    JOB = {'state': 'running', 'kind': kind, 'stage': 'queued', 'detail': 'Waiting for the supervisor.', 'started': admin_metrics.timestamp()}
    threading.Thread(target=job_runner, args=(kind, archive), daemon=True).start()
    return JOB


def api(method, path, query, payload):
    if method == 'GET' and path == '/api/console/runs':
        return console_sources()
    if method == 'GET' and path == '/api/console':
        return console_output(query)
    if method == 'POST' and path == '/api/console':
        return send_console(payload)
    if method == 'GET' and path == '/api/status':
        healthy = health()
        return {'healthy': healthy, 'mods': running_mods(healthy), 'backups': admin_metrics.inventory(), 'job': JOB,
                'version': Path('/terraria-server/VERSION').read_text().strip()
                if Path('/terraria-server/VERSION').exists() else 'development'}
    if method == 'GET' and path == '/api/settings':
        return configuration()
    if method == 'GET' and path == '/api/workshop':
        return workshop.query(query.get('q', [''])[0], query.get('sort', ['popular'])[0],
                              int(query.get('page', ['1'])[0]), query.get('tag', [''])[0])
    if method == 'POST' and path == '/api/workshop/lookup':
        return workshop.lookup(str(payload.get('value', '')))
    if method == 'POST' and path == '/api/settings':
        if not settings.web_mode():
            raise ValueError('Enable TMOD_CONFIG_SOURCE=web in Compose to edit settings.')
        with STATE_LOCK:
            if JOB.get('state') == 'running' or settings.read_json(admin_metrics.STATE).get('state') == 'running':
                raise ValueError('Wait for the current operation before changing settings.')
            current = configuration()
            if payload.get('revision') != current['revision']:
                raise ValueError('Settings changed in another session. Reload before saving.')
            removed = []
            values = settings.clean_mod_selection(settings.validate(payload.get('settings')), removed)
            settings.atomic_json(settings.PENDING, {**current['staged'], **values})
            notice_path = settings.PENDING.with_name('pending-removed.json')
            previous = settings.read_json(notice_path).get('names', [])
            settings.atomic_json(notice_path, {'names': sorted(set(previous + removed))})
        return configuration()
    if method == 'POST' and path in ('/api/backup', '/api/apply', '/api/verify'):
        if payload.get('confirm') is not True:
            raise ValueError('Explicit confirmation is required.')
        kind = path.rsplit('/', 1)[-1]
        with STATE_LOCK:
            if kind == 'apply' and (not settings.web_mode() or not settings.PENDING.exists()):
                raise ValueError('No staged web-managed settings to apply.')
            if kind == 'apply' and payload.get('revision') != configuration()['revision']:
                raise ValueError('The staged draft changed. Reload and review it before applying.')
            archive = None
            if kind == 'verify':
                name = payload.get('archive', '')
                if not isinstance(name, str) or not name.startswith('tmod-backup-') or Path(name).name != name or '/' in name or '\\' in name:
                    raise ValueError('Invalid archive name.')
                archive = admin_metrics.DEST / name
                if archive.is_symlink() or not archive.is_dir():
                    raise ValueError('Archive not found.')
            return start_job(kind, archive)
    raise LookupError('Endpoint not found.')


def application(environ, start_response):
    status, content_type = '200 OK', 'application/json; charset=utf-8'
    headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
               ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
               ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://*.steamusercontent.com https://*.steamstatic.com https://*.akamaihd.net; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
    path, method = environ.get('PATH_INFO', '/'), environ['REQUEST_METHOD']
    try:
        origin = os.environ.get('TMOD_WEB_ORIGIN', 'http://localhost:8080').rstrip('/')
        if environ.get('HTTP_ORIGIN') not in (None, origin):
            raise PermissionError('Cross-origin requests are not allowed.')
        if environ.get('HTTP_HOST') != urllib.parse.urlsplit(origin).netloc:
            raise PermissionError('Unexpected host. Configure TMOD_WEB_ORIGIN for this address.')
        if path.startswith('/api/'):
            supplied = environ.get('HTTP_AUTHORIZATION', '')
            if not TOKEN or not hmac.compare_digest(supplied.encode(), ('Bearer ' + TOKEN).encode()):
                raise PermissionError('Authentication required.')
            payload = {}
            if method == 'POST':
                length = int(environ.get('CONTENT_LENGTH') or '0')
                if not 0 < length <= 65536 or environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                    raise ValueError('Expected a JSON body of at most 64 KiB.')
                payload = json.loads(environ['wsgi.input'].read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object.')
            body = json.dumps(api(method, path, urllib.parse.parse_qs(environ.get('QUERY_STRING', '')), payload)).encode()
        elif method == 'GET' and path in ('/', '/app.js', '/style.css'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
            content_type = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path] + '; charset=utf-8'
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


def main():
    global TOKEN
    TOKEN = Path(os.environ['TMOD_WEB_TOKEN_FILE']).read_text().strip()
    if len(TOKEN) < 32 or len(TOKEN) > 256 or not TOKEN.isascii() or any(c.isspace() for c in TOKEN):
        raise ValueError('Admin token must contain 32–256 non-whitespace ASCII characters.')
    origin = urllib.parse.urlsplit(os.environ.get('TMOD_WEB_ORIGIN', 'http://localhost:8080'))
    if origin.scheme not in ('http', 'https') or not origin.hostname or origin.username or origin.password or origin.path not in ('', '/') or origin.query or origin.fragment:
        raise ValueError('TMOD_WEB_ORIGIN must be an http(s) origin without a path or credentials.')
    from waitress import serve
    print('[ADMIN] Private administration interface listening on port 8080.', flush=True)
    serve(application, host='0.0.0.0', port=8080, threads=4, connection_limit=32,
          channel_timeout=30, max_request_body_size=65536, clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
