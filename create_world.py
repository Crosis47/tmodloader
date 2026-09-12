"""Create an explicitly selected evil through the dedicated server's menu.

The generated config opts in with a comment; custom configs are untouched.
The creation child never selects a playable world or opens a game listener.
"""
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time


def drive(child, answers, timeout=3600, encoding='utf-8'):
    output = queue.Queue(maxsize=256)

    def read():
        while True:
            chunk = child.stdout.read(1)
            output.put(chunk)
            if not chunk:
                return

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    buffer = ''
    for pattern, answer in answers:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('World creation timed out; inspect the console log.')
            try:
                chunk = output.get(timeout=min(remaining, 1))
            except queue.Empty:
                continue
            if not chunk:
                raise RuntimeError(f'World creator exited before prompt {pattern!r}.')
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            buffer = (buffer + chunk.decode('utf-8', errors='replace'))[-8192:]
            if re.search(pattern, buffer, re.IGNORECASE):
                buffer = ''
                if answer is not None:
                    child.stdin.write((answer + '\n').encode(encoding))
                    child.stdin.flush()
                break


def create(config_path, command):
    lines = Path(config_path).read_text().splitlines()
    evil = next((line.partition('=')[2] for line in lines
                 if line.startswith('# tmod-worldevil=')), 'random')
    if evil == 'random':
        return
    if evil not in ('corruption', 'crimson'):
        raise ValueError('Unsupported world evil in generated config.')
    values = dict(line.split('=', 1) for line in lines if '=' in line and not line.startswith('#'))
    world = Path(values['world'])
    if world.exists():
        return
    name, seed = values['worldname'], values.get('seed', '')
    # Terraria checks .NET string lengths (UTF-16 code units).
    if not name.strip() or len(name.encode('utf-16-le')) > 52 or len(seed.encode('utf-16-le')) > 78:
        raise ValueError('Interactive generation requires a nonblank name up to 26 characters and seed up to 39 characters.')
    print(f'[WORLDGEN] Creating {name} with {evil}; waiting for generation and save to finish.', flush=True)
    with tempfile.TemporaryDirectory(prefix='tmod-worldgen-') as directory:
        temporary = Path(directory) / 'serverconfig.txt'
        # Preserve mod selection/path settings, but prevent automatic world loading.
        omitted = {'world', 'worldname', 'autocreate', 'seed', 'language', 'worldpath'}
        temporary.write_text('\n'.join(line for line in lines
                                      if not line.startswith('#') and line.partition('=')[0] not in omitted)
                             + f'\nworldpath={world.parent}/\nlanguage=en-US\n')
        temporary.chmod(0o600)
        args = list(command)
        args[args.index('-config') + 1] = str(temporary)
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, bufsize=0)
        previous = signal.getsignal(signal.SIGTERM)

        def interrupted(signum, frame):
            raise RuntimeError('World creation interrupted.')

        signal.signal(signal.SIGTERM, interrupted)
        try:
            drive(child, [
                (r'Choose world\s*:', 'n'),
                (r'Choose size\s*:', values['autocreate']),
                (r'Choose difficulty\s*:', str(int(values['difficulty']) + 1)),
                (r'Choose (?:world )?evil\s*:', {'corruption': '2', 'crimson': '3'}[evil]),
                (r'Enter world name\s*:', name),
                (r'Enter seed(?:\s*\([^\r\n]*\))?\s*:', seed),
                (r'Choose world\s*:', None),
            ], encoding='utf-16-le' if os.name == 'nt' else 'utf-8')
            if not world.is_file() or world.stat().st_size == 0:
                raise RuntimeError(f'Creator returned to the menu without saving expected world: {world}')
        finally:
            # The final menu is reached only after the generation/save task finishes.
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            child.stdin.close()
            child.stdout.close()
            signal.signal(signal.SIGTERM, previous)
    print('[WORLDGEN] World saved; starting the configured game server.', flush=True)


if __name__ == '__main__':
    try:
        create(sys.argv[1], sys.argv[2:])
    except Exception as error:
        print(f'[WORLDGEN] FATAL: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
    # Keep the game in the runner's process group and propagate its exit status.
    # subprocess.call also preserves exit status on Windows validation hosts.
    sys.exit(subprocess.call(sys.argv[2:]))
