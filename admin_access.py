"""Dashboard transport and browser-origin checks using the actual socket peer."""
import ipaddress
import os
import urllib.parse

HTTP_NETWORKS = tuple(map(ipaddress.ip_network, (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '::1/128',
)))


def address(value):
    parsed = ipaddress.ip_address(value)
    return getattr(parsed, 'ipv4_mapped', None) or parsed


def origin_parts(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment or
            any(c.isspace() for c in value) or '\\' in value):
        raise ValueError('TMOD_WEB_ORIGIN must be an http(s) origin without a path or credentials.')
    parsed.port
    return parsed


def validate_config():
    if os.environ.get('TMOD_WEB_ORIGIN'):
        origin_parts(os.environ['TMOD_WEB_ORIGIN'])
    if os.environ.get('TMOD_WEB_TRUSTED_PROXY'):
        address(os.environ['TMOD_WEB_TRUSTED_PROXY'])


def check_request(environ):
    try:
        source = address(environ.get('REMOTE_ADDR', ''))
    except ValueError:
        raise PermissionError('Cannot determine client address; access denied.') from None
    scheme = environ.get('wsgi.url_scheme', 'http')
    proxy = os.environ.get('TMOD_WEB_TRUSTED_PROXY', '')
    if proxy and source == address(proxy):
        # A single explicitly trusted proxy must overwrite these headers.
        # Missing headers and multi-hop chains fail closed.
        try:
            source = address(environ.get('HTTP_X_FORWARDED_FOR', ''))
        except ValueError:
            raise PermissionError('Trusted proxy must send one client IP in X-Forwarded-For.') from None
        scheme = environ.get('HTTP_X_FORWARDED_PROTO', '')
        if scheme not in ('http', 'https'):
            raise PermissionError('Trusted proxy must send X-Forwarded-Proto: http or https.')
    elif any(key == 'HTTP_FORWARDED' or key.startswith('HTTP_X_FORWARDED_') for key in environ):
        raise PermissionError('Forwarded headers require TMOD_WEB_TRUSTED_PROXY to match the proxy IP.')
    if scheme != 'https' and not any(source in network for network in HTTP_NETWORKS):
        raise PermissionError('HTTPS is required outside RFC 1918 private networks and loopback.')

    host = environ.get('HTTP_HOST', '')
    origin = os.environ.get('TMOD_WEB_ORIGIN', '').rstrip('/')
    if not origin:
        origin = scheme + '://' + host
        parsed = origin_parts(origin)
        # Literal addresses and localhost work without configuration; arbitrary
        # DNS names need an explicit origin to retain DNS-rebinding protection.
        if parsed.hostname != 'localhost':
            try:
                address(parsed.hostname)
            except ValueError:
                raise PermissionError('Open the server IP address, or set TMOD_WEB_ORIGIN for this hostname.') from None
    if host != origin_parts(origin).netloc:
        raise PermissionError('Unexpected host. Configure TMOD_WEB_ORIGIN for this address.')
    if environ.get('HTTP_ORIGIN') not in (None, origin):
        raise PermissionError('Cross-origin requests are not allowed.')
