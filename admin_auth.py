"""Argon2id credentials and interactive container provisioning."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import tempfile

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import VerificationError, InvalidHash as InvalidHashError

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)


def token_path():
    return Path(os.environ.get('TMOD_WEB_TOKEN_FILE') or '/data/admin/token.argon2')


def validate_token(token):
    if not 8 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('Admin token must contain 8–256 non-whitespace ASCII characters.')


def read_hash(path):
    encoded = path.read_text(encoding='ascii').strip()
    try:
        params = extract_parameters(encoded)
        if (params.type != Type.ID or params.version != 19 or
                not 19456 <= params.memory_cost <= 262144 or
                not 2 <= params.time_cost <= 10 or not 1 <= params.parallelism <= 8 or
                params.salt_len < 16 or params.hash_len < 16):
            raise ValueError('Unsupported Argon2id parameters.')
        # Check the complete encoding, including base64.
        try:
            HASHER.verify(encoded, 'validation-probe')
        except VerificationError as error:
            from argon2.exceptions import VerifyMismatchError
            if not isinstance(error, VerifyMismatchError):
                raise ValueError('Malformed Argon2id hash.') from error
    except InvalidHashError as error:
        raise ValueError('Expected a valid Argon2id hash.') from error
    return encoded


def verify(encoded, token):
    try:
        validate_token(token)
        return HASHER.verify(encoded, token)
    except (ValueError, VerificationError, InvalidHashError):
        return False


def save_token(path, token):
    validate_token(token)
    encoded = HASHER.hash(token)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.token-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(encoded + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup'])
    parser.add_argument('--file', type=Path)
    args = parser.parse_args()
    path = args.file or token_path()
    if args.action == 'setup':
        if not sys.stdin.isatty():
            raise ValueError('Setup requires an interactive terminal (docker compose exec -it).')
        token = getpass.getpass('Admin token (8–256 characters): ')
        validate_token(token)
        if token != getpass.getpass('Confirm admin token: '):
            raise ValueError('Tokens do not match; no changes saved.')
        save_token(path, token)
        print('Argon2id hash saved. Restart an already-running dashboard to rotate credentials.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(f'[ADMIN] {error}')
