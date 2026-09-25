"""Cold-backup scheduling using the same calendar rules as restarts."""
import sys
import time

import admin_settings as settings
from admin_restart import build_schedule


def status():
    return settings.read_json(settings.RUNTIME / 'backup-schedule.json',
                              {'state': 'disabled', 'next_at': None, 'detail': 'Scheduled backups are disabled.'})


def reset():
    value = build_schedule('BACKUP')
    value['detail'] = 'Waiting for the next backup.' if value['state'] == 'scheduled' else 'Scheduled backups are disabled.'
    settings.atomic_json(settings.RUNTIME / 'backup-schedule.json', value)


def due():
    value = status()
    return value.get('state') == 'scheduled' and (time.time() >= value['next_at']
        if value['mode'] in ('daily', 'weekly', 'monthly') else time.monotonic() >= value['deadline'])


if __name__ == '__main__':
    if sys.argv[1] == 'reset':
        reset()
    elif sys.argv[1] == 'enabled':
        sys.exit(0 if build_schedule('BACKUP')['state'] == 'scheduled' else 1)
    else:
        sys.exit(0 if due() else 1)
