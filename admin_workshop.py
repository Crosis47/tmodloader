"""Fixed-endpoint Workshop queries; never fetch user-supplied URLs."""
import base64
from contextvars import ContextVar
from contextlib import contextmanager
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet, InvalidToken

import json
import os
from pathlib import Path
import re
import threading
import tempfile
import time
import urllib.parse
import urllib.request

APP_ID = 1281930
CACHE = {}
LOCK = threading.Lock()
CREDENTIAL = ContextVar('workshop_admin_token', default='')


@contextmanager
def authenticated(token):
    """Keep credentials local to the authenticated request, including concurrent requests."""
    context = CREDENTIAL.set(token)
    try:
        yield
    finally:
        CREDENTIAL.reset(context)


def cipher(salt):
    token = CREDENTIAL.get()
    if not token:
        raise ValueError('Sign in to unlock the Workshop key.')
    derived = hash_secret_raw(b'tmod-workshop-v1\0' + token.encode('utf-8'), salt,
                              time_cost=3, memory_cost=65536, parallelism=4,
                              hash_len=32, type=Type.ID)
    return Fernet(base64.urlsafe_b64encode(derived))


def store_encrypted(value):
    salt = os.urandom(16)
    encoded = json.dumps({'version': 1, 'salt': base64.b64encode(salt).decode('ascii'),
                          'ciphertext': cipher(salt).encrypt(value.encode('ascii')).decode('ascii')})
    path = managed_key_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.workshop-key-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
            stream.write(encoded + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def steam(path, parameters, post=False):
    encoded = urllib.parse.urlencode(parameters).encode()
    url = 'https://api.steampowered.com/' + path
    request = urllib.request.Request(url if post else url + '?' + encoded.decode(),
                                     data=encoded if post else None,
                                     headers={'User-Agent': 'tmodloader-admin/1.0'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError('Steam response exceeded the size limit.')
            return json.loads(body)
    except Exception:
        # urllib errors may contain a query URL with the API key.
        raise ValueError('Steam request failed. Check connectivity, API key, and Steam availability.') from None


def managed_key_path():
    return Path(os.environ.get('TMOD_DATA_DIR', '/data')) / '.tmod-control/workshop.key'


def read_key():
    path = managed_key_path()
    managed = path.exists()
    if not managed:
        path = Path(os.environ.get('TMOD_WORKSHOP_KEY_FILE') or '/nonexistent-workshop-key')
    try:
        with path.open(encoding='ascii') as stream:
            value = stream.read(4097).strip()
        if len(value) > 4096:
            raise ValueError('Workshop key file exceeds the size limit.')
    except OSError:
        if managed:
            raise ValueError('Cannot read the saved Workshop key. Check file permissions.') from None
        return ''
    if managed and value.startswith('{'):
        try:
            envelope = json.loads(value)
            salt = base64.b64decode(envelope['salt'], validate=True)
            if envelope['version'] != 1 or len(salt) != 16:
                raise ValueError('Invalid envelope')
            return cipher(salt).decrypt(envelope['ciphertext'].encode('ascii')).decode('ascii')
        except (ValueError, KeyError, TypeError, InvalidToken):
            raise ValueError('The saved Workshop key cannot be unlocked. If the admin token changed, enter and save the Steam API key again.') from None
    if managed and value:
        # Upgrade a previously saved plaintext key atomically on authenticated use.
        if not CREDENTIAL.get():
            raise ValueError('Sign in to encrypt the existing Workshop key.')
        with LOCK:
            # Re-read under the lock so a concurrent save cannot be overwritten.
            if path.read_text(encoding='ascii').strip() != value:
                raise ValueError('Workshop key changed; retry the request.')
            store_encrypted(value)
    return value


def key_available():
    try:
        return bool(read_key())
    except ValueError:
        return False


def save_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', value.strip()):
        raise ValueError('Enter a 32-character hexadecimal Steam Web API key.')
    value = value.strip()
    response = steam('IPublishedFileService/QueryFiles/v1/', {
        'key': value, 'input_json': json.dumps({'appid': APP_ID, 'query_type': 0,
                                             'page': 1, 'numperpage': 1})}).get('response', {})
    if 'publishedfiledetails' not in response and response.get('total', -1) != 0:
        raise ValueError('Steam did not accept this key for Workshop search. The previous key was not changed.')
    with LOCK:
        store_encrypted(value)
        CACHE.clear()
    return {'saved': True}


def card(item):
    if int(item.get('consumer_app_id', item.get('consumer_appid', 0))) != APP_ID:
        return None
    if item.get('result', 1) != 1:
        return None
    if item.get('file_type', 0) not in (0, 2):
        return None
    identity = str(item.get('publishedfileid', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,19}', identity):
        return None
    preview = item.get('preview_url', '')
    parsed = urllib.parse.urlsplit(preview)
    if parsed.scheme != 'https' or not any((parsed.hostname or '').endswith('.' + domain)
                                            for domain in ('steamusercontent.com', 'steamstatic.com', 'akamaihd.net')):
        preview = ''
    description = str(item.get('short_description', item.get('description', '')))
    description = re.sub(r'\[img\].*?\[/img\]', '', description, flags=re.DOTALL | re.IGNORECASE)
    description = re.sub(r'\[/?[^\]]+\]', '', description)
    content = Path(os.environ.get('TMOD_DATA_DIR', '/data')) / 'steamMods/steamapps/workshop/content' / str(APP_ID) / identity
    tags = {str(tag.get('tag', '') if isinstance(tag, dict) else tag).casefold() for tag in (item.get('tags') or [])}
    client_only = item.get('file_type', 0) != 2 and 'client' in tags and not tags.intersection({'both', 'server'})
    return {'id': identity, 'title': str(item.get('title', identity))[:300],
            'client_only': client_only,
            'description': description[:1200], 'downloaded': content.is_dir(),
            'preview': preview, 'updated': item.get('time_updated'),
            'subscriptions': item.get('subscriptions'),
            'votes': item.get('vote_data', {}),
            'collection': item.get('file_type') == 2,
            'url': 'https://steamcommunity.com/sharedfiles/filedetails/?id=' + identity}


def query(text='', sort='popular', page=1, tag=''):
    if sort not in ('popular', 'newest', 'updated') or not 1 <= page <= 100 or len(text) > 150 or len(tag) > 80:
        raise ValueError('Invalid Workshop search parameters.')
    key = read_key()
    if not key:
        raise ValueError('Enter a Steam API key on the Workshop page to browse. URL/ID imports work without it.')
    cache_key = (text, sort, page, tag)
    with LOCK:
        entry = CACHE.get(cache_key)
        if entry and time.monotonic() - entry[0] < 120:
            return entry[1]
    parameters = {'key': key, 'input_json': json.dumps({
        'appid': APP_ID, 'query_type': {'popular': 0, 'newest': 1, 'updated': 21}[sort],
        'page': page, 'numperpage': 20, 'search_text': text,
        'requiredtags': [tag] if tag else [], 'return_vote_data': True,
        'return_short_description': True, 'return_previews': True, 'return_tags': True})}
    response = steam('IPublishedFileService/QueryFiles/v1/', parameters).get('response', {})
    if 'publishedfiledetails' not in response and response.get('total', -1) != 0:
        raise ValueError('Steam did not return Workshop results; verify the API key has access.')
    result = {'items': [value for item in response.get('publishedfiledetails', []) if (value := card(item))],
              'total': response.get('total', 0), 'page': page}
    with LOCK:
        if len(CACHE) >= 100:
            CACHE.clear()
        CACHE[cache_key] = (time.monotonic(), result)
    return result


def lookup(value):
    if re.fullmatch(r'[1-9][0-9]{0,19}', value):
        identity = value
    else:
        url = urllib.parse.urlsplit(value)
        if url.scheme != 'https' or url.hostname != 'steamcommunity.com' or url.path not in ('/sharedfiles/filedetails/', '/workshop/filedetails/'):
            raise ValueError('Enter a Workshop ID or an https://steamcommunity.com Workshop item URL.')
        identity = urllib.parse.parse_qs(url.query).get('id', [''])[0]
        if not re.fullmatch(r'[1-9][0-9]{0,19}', identity):
            raise ValueError('Invalid Workshop ID.')
    response = steam('ISteamRemoteStorage/GetPublishedFileDetails/v1/',
                     {'itemcount': 1, 'publishedfileids[0]': identity}, post=True)
    items = response.get('response', {}).get('publishedfiledetails', [])
    value = card(items[0]) if items else None
    if not value:
        raise ValueError('This is not an accessible tModLoader Workshop item.')
    return value


def dependencies(identity):
    """Resolve the complete Workshop child graph without modifying selections."""
    if not re.fullmatch(r'[1-9][0-9]{0,19}', str(identity)):
        raise ValueError('Invalid Workshop ID.')
    key = read_key()
    if not key:
        return {'checked': False, 'items': [], 'excluded': []}
    pending, seen, found, excluded = [str(identity)], set(), [], []
    deadline = time.monotonic() + 45
    while pending:
        if time.monotonic() > deadline:
            raise ValueError('Dependency check timed out. No mods were added; try again.')
        batch, pending = pending[:50], pending[50:]
        response = steam('IPublishedFileService/GetDetails/v1/', {
            'key': key, 'input_json': json.dumps({'publishedfileids': batch,
                                                'includechildren': True, 'includetags': True})})
        details = response.get('response', {}).get('publishedfiledetails', [])
        by_id = {str(item.get('publishedfileid')): item for item in details}
        for item_id in batch:
            raw = by_id.get(item_id, {})
            item = card(raw)
            if not item:
                raise ValueError('Cannot check Workshop item ' + item_id + '. It may be private, unavailable, or for another game. No mods were added.')
            seen.add(item_id)
            if item_id != str(identity):
                (excluded if item['client_only'] else found).append(item)
            if item['client_only']:
                continue
            for child in raw.get('children', []):
                child_id = str(child.get('publishedfileid', ''))
                if not re.fullmatch(r'[1-9][0-9]{0,19}', child_id):
                    raise ValueError('Steam returned an invalid dependency ID. No mods were added.')
                if child_id not in seen and child_id not in pending and child_id not in batch:
                    pending.append(child_id)
            if len(seen) + len(pending) > 250:
                raise ValueError('Dependency graph exceeds 250 items. No mods were added.')
    return {'checked': True, 'items': found, 'excluded': excluded}
