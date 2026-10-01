"""Bounded listener regression against an isolated Docker server on host loopback.

Usage: python tests/listener-integration-test.py IMAGE [RUNTIME_TAG]
"""
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup


def exercise(name):
    info = json.loads(backup.docker('inspect', name))[0]
    binding = info['NetworkSettings']['Ports']['7777/tcp'][0]
    assert binding['HostIp'] == '127.0.0.1', 'Test must stay on loopback'
    address = ('127.0.0.1', int(binding['HostPort']))
    backup.wait_healthy(name, 600)
    assert 'Container TCP listener lifecycle enabled.' in backup.docker(
        'exec', name, 'cat', '/data/tModLoader/Logs/server.log')
    pid = backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid')
    for cycle in range(3):
        clients = []
        try:
            for index in range(12):
                try:
                    client = socket.create_connection(address, timeout=1)
                    clients.append(client)
                    if cycle == 1:
                        client.sendall(b'\x00\x00\x01')
                except OSError:
                    pass  # The server may close admission while all slots are occupied.
                time.sleep(.1)
            assert clients, 'No connections reached the listener'
            time.sleep(3)
        finally:
            for client in clients:
                client.close()
        backup.wait_healthy(name, 60)
        assert backup.docker('exec', name, 'cat', '/tmp/tmodloader/server.pid') == pid
        # A vanilla greeting gets a protocol response from tML, proving that
        # admission and packet processing still work after slots become free.
        greeting = b'Terraria279'
        packet = b'\x01' + bytes([len(greeting)]) + greeting
        with socket.create_connection(address, timeout=5) as client:
            client.settimeout(10)
            client.sendall(struct.pack('<H', len(packet) + 2) + packet)
            assert client.recv(4096), 'Game did not respond to a new client'
        time.sleep(2)
        print('Listener recovered without game restart: cycle', cycle + 1, flush=True)
    log = backup.docker('exec', name, 'cat', '/data/tModLoader/Logs/server.log')
    assert 'Not listening. You must call the Start()' not in log
    backup.docker('exec', name, 'inject', 'save')
    deadline = time.monotonic() + 30
    while True:
        current_log = backup.docker('exec', name, 'cat', '/data/tModLoader/Logs/server.log')
        if 'Saving modded world data' in current_log[len(log):]:
            break
        if time.monotonic() > deadline:
            raise AssertionError('World save did not complete after connection test')
        time.sleep(1)
    print('Connection handling and save command passed; game process unchanged.', flush=True)


if __name__ == '__main__':
    name = 'tmod-listener-test-' + uuid.uuid4().hex[:10]
    try:
        backup.docker('run', '-d', '--name', name, '-p', '127.0.0.1::7777',
                      '-v', '/data', '-v', '/backups', '-e', 'TMOD_GITHUB_TOKEN', '-e', 'TMOD_WEB_ENABLED=0',
                      '-e', 'TMOD_AUTO_UPDATE=0', '-e', 'TMOD_UPDATE_VERSION=' + (sys.argv[2] if len(sys.argv) > 2 else 'v2026.07.3.0'),
                      '-e', 'TMOD_WORLDSIZE=1', '-e', 'TMOD_AUTOSAVE_INTERVAL=0', sys.argv[1])
        exercise(name)
    finally:
        backup.docker('rm', '-f', '-v', name)
