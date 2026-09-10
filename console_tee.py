"""Preserve raw output while recording the first received output timestamp."""
import datetime
import os
import time
from pathlib import Path
import sys


def copy_output(source, target, destination):
    first = True
    with target.open('wb', buffering=0) as log:
        while chunk := source.read1(65536):
            if first:
                target.with_name(target.name + '.first').write_text(
                    datetime.datetime.now(datetime.timezone.utc).isoformat())
                first = False
            log.write(chunk)
            # Explicit nanoseconds avoid coarse filesystem write times appearing
            # earlier than the first-output marker for very short runs.
            written = time.time_ns()
            os.utime(target, ns=(written, written))
            destination.write(chunk)
            destination.flush()


if __name__ == '__main__':
    copy_output(sys.stdin.buffer, Path(sys.argv[1]), sys.stdout.buffer)
