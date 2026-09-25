"""Preserve raw output while recording the first received output timestamp."""
import datetime
import os
import time
from pathlib import Path
import sys
import admin_logs


def copy_output(source, target, destination, tracker=None, player_tracker=None):
    first = True
    tail = b''
    _, _, rotation_size = admin_logs.limits()
    last_cleanup = time.monotonic()
    with target.open('wb', buffering=0) as log:
        while chunk := source.read1(65536):
            if log.tell() and log.tell() + len(chunk) > rotation_size:
                # The stream remains open for the whole process; replace its fd
                # after moving the completed segment into console history.
                admin_logs.rotate(target)
                with target.open('wb', buffering=0) as fresh:
                    os.dup2(fresh.fileno(), log.fileno())
                first = True
            if time.monotonic() - last_cleanup >= 60:
                admin_logs.prune(target.parent)
                last_cleanup = time.monotonic()
            if first:
                target.with_name(target.name + '.first').write_text(
                    datetime.datetime.now(datetime.timezone.utc).isoformat())
                first = False
            log.write(chunk)
            if player_tracker is not None:
                player_tracker.feed(chunk)
            if tracker is not None:
                combined = tail + chunk
                if b'\nServer started\n' in b'\n' + combined.replace(b'\r\n', b'\n'):
                    try:
                        tracker.start()
                    except (OSError, ValueError) as error:
                        print(f'[ADMIN] World uptime tracking unavailable: {error}', file=sys.stderr, flush=True)
                        tracker = None
                tail = combined[-128:]
            # Explicit nanoseconds avoid coarse filesystem write times appearing
            # earlier than the first-output marker for very short runs.
            written = time.time_ns()
            os.utime(target, ns=(written, written))
            destination.write(chunk)
            destination.flush()


if __name__ == '__main__':
    from admin_player_history import VisitTracker
    from admin_world_time import SessionTracker
    name = os.environ.get('TMOD_WORLDNAME')
    custom = os.environ.get('TMOD_USECONFIGFILE', 'No').lower() in ('yes', 'true', '1')
    tracker = SessionTracker(name) if name and not custom else None
    player_tracker = VisitTracker(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        copy_output(sys.stdin.buffer, Path(sys.argv[1]), sys.stdout.buffer, tracker, player_tracker)
    finally:
        if tracker:
            tracker.finish()
        if player_tracker:
            try:
                player_tracker.finish()
            except OSError as error:
                print(f'[ADMIN] Player history session could not close: {error}', file=sys.stderr, flush=True)
