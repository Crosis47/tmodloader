"""Fixed-endpoint Workshop queries; never fetch user-supplied URLs."""
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.parse
import urllib.request

APP_ID = 1281930
CACHE = {}
LOCK = threading.Lock()


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


def key_available():
    try:
        with Path(os.environ.get('TMOD_WORKSHOP_KEY_FILE', '')).open() as stream:
            return bool(stream.read(4096).strip())
    except (OSError, ValueError):
        return False


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
    if not key_available():
        raise ValueError('Workshop browsing requires TMOD_WORKSHOP_KEY_FILE. URL/ID imports work without it.')
    cache_key = (text, sort, page, tag)
    with LOCK:
        entry = CACHE.get(cache_key)
        if entry and time.monotonic() - entry[0] < 120:
            return entry[1]
    key = Path(os.environ['TMOD_WORKSHOP_KEY_FILE']).read_text().strip()
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
