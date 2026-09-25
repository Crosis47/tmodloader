"""Bounded console archives; never prune game logs, active logs, or symlinks."""
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import admin_settings as settings

ARCHIVE = re.compile(r'run-\d{8}T\d{6}Z-[A-Za-z0-9_]+\.log')


def limits():
    values = settings.validate({key: os.environ.get(key, default) for key, default in (
        ('TMOD_LOG_RETENTION_DAYS', '30'), ('TMOD_LOG_HISTORY_MAX_MB', '512'), ('TMOD_LOG_ROTATE_MB', '64'))})
    return (int(values['TMOD_LOG_RETENTION_DAYS']) * 86400,
            int(values['TMOD_LOG_HISTORY_MAX_MB']) * 1048576, int(values['TMOD_LOG_ROTATE_MB']) * 1048576)


def prune(directory, now=None):
    age, budget, _ = limits()
    history = Path(directory) / 'console-history'
    if history.is_symlink() or not history.is_dir():
        return
    now = time.time() if now is None else now
    candidates = []
    for path in history.iterdir():
        if path.is_symlink() or not path.is_file() or not ARCHIVE.fullmatch(path.name):
            continue
        info = path.stat()
        candidates.append((info.st_mtime, path, info.st_size))
    total = sum(size for _, _, size in candidates)
    for modified, path, size in sorted(candidates):
        if (age and now - modified > age) or (budget and total > budget):
            path.unlink()
            marker = path.with_name(path.name + '.first')
            if not marker.is_symlink():
                marker.unlink(missing_ok=True)
            total -= size


def rotate(target):
    target = Path(target)
    history = target.parent / 'console-history'
    if history.is_symlink() or target.is_symlink():
        raise ValueError('Console log paths must not be symlinks.')
    history.mkdir(exist_ok=True)
    prefix = 'run-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-'
    fd, name = tempfile.mkstemp(prefix=prefix, suffix='.log', dir=history)
    os.close(fd)
    archive = Path(name)
    target.replace(archive)
    marker = target.with_name(target.name + '.first')
    if marker.is_file() and not marker.is_symlink():
        marker.replace(archive.with_name(archive.name + '.first'))
    prune(target.parent)


if __name__ == '__main__':
    prune(Path(sys.argv[1]))
