"""Checkpoint world-loaded time from the game's console lifecycle."""
import datetime
import hashlib
import os
from pathlib import Path
import sys
import threading
import time

import admin_settings as settings

CHECKPOINT_SECONDS = 5


def record_path(name):
    settings.validate({'TMOD_WORLDNAME': name})
    return settings.DATA / 'admin/world-uptime' / (hashlib.sha256(name.encode()).hexdigest() + '.json')


def process_identity(pid):
    try:
        fields = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(') ', 1)[1].split()
        if fields[0] in ('Z', 'X'):
            return None
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + fields[19]
    except (OSError, ValueError, IndexError):
        return None


def read(name):
    try:
        saved = settings.read_json(record_path(name))
        if not saved:
            return {'total_uptime_seconds': None, 'session_uptime_seconds': None, 'uptime_tracked_since': None}
        elapsed = None
        total = float(saved['total_seconds'])
        if saved.get('active') and saved.get('owner_identity') and process_identity(saved['owner_pid']) == saved['owner_identity']:
            elapsed = max(0, time.monotonic() - saved['started_monotonic'])
            total += max(0, elapsed - saved['session_seconds'])
        return {'total_uptime_seconds': int(total), 'session_uptime_seconds': int(elapsed) if elapsed is not None else None,
                'uptime_tracked_since': saved['tracked_since']}
    except (OSError, ValueError, KeyError, TypeError):
        return {'total_uptime_seconds': None, 'session_uptime_seconds': None, 'uptime_tracked_since': None}


class SessionTracker:
    def __init__(self, name):
        self.name = name
        self.started = None
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if self.started is not None:
            return
        saved = settings.read_json(record_path(self.name))
        self.base = float(saved.get('total_seconds', 0))
        self.tracked_since = saved.get('tracked_since') or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.identity = process_identity(os.getpid())
        self.started = time.monotonic()
        self.checkpoint()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def checkpoint(self, active=True):
        elapsed = max(0, time.monotonic() - self.started)
        settings.atomic_json(record_path(self.name), {
            'total_seconds': self.base + elapsed, 'tracked_since': self.tracked_since,
            'active': active, 'session_seconds': elapsed, 'started_monotonic': self.started,
            'owner_pid': os.getpid(), 'owner_identity': self.identity})

    def run(self):
        while not self.stop.wait(CHECKPOINT_SECONDS):
            self.safe_checkpoint()

    def safe_checkpoint(self, active=True):
        try:
            self.checkpoint(active)
        except OSError as error:
            print(f'[ADMIN] World uptime checkpoint failed: {error}', file=sys.stderr, flush=True)

    def finish(self):
        if self.stop.is_set():
            return
        self.stop.set()
        if self.thread:
            self.thread.join()
        if self.started is not None:
            self.safe_checkpoint(active=False)
