"""Restart timer shared by the supervisor and administration worker."""
import os
import sys
import time
import calendar
import contextlib
import fcntl
import math
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import admin_settings as settings


def status():
    return settings.read_json(settings.RUNTIME / 'restart-schedule.json',
                              {'state': 'disabled', 'next_at': None, 'detail': 'Scheduled restarts are disabled.'})


def next_calendar(now, clock, timezone, mode='daily', weekday='sunday', monthday=1):
    zone = ZoneInfo(timezone)
    local = datetime.fromtimestamp(now, zone)
    hour, minute = map(int, clock.split(':'))
    weekdays = settings.CHOICES['TMOD_RESTART_WEEKDAY']
    for offset in range(63):
        day = local.date() + timedelta(days=offset)
        if mode == 'weekly' and day.weekday() != weekdays.index(weekday):
            continue
        if mode == 'monthly' and day.day != min(monthday, calendar.monthrange(day.year, day.month)[1]):
            continue
        # fold=0 selects the first occurrence when clocks move back. A missing
        # spring-forward time is shifted forward by the daylight-saving gap.
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0).timestamp()
        if candidate > now:
            return candidate
    raise ValueError('Could not determine the next calendar restart.')


def next_daily(now, clock, timezone):
    return next_calendar(now, clock, timezone)


def build_schedule(prefix="RESTART", values=None):
    values = os.environ if values is None else values
    mode = values.get('TMOD_' + prefix + '_MODE', 'interval' if prefix == 'BACKUP' else 'disabled')
    interval = int(values.get('TMOD_' + prefix + '_INTERVAL', '0')) * 60
    clock = values.get('TMOD_' + prefix + '_TIME', '04:00')
    timezone = values.get('TMOD_' + prefix + '_TIMEZONE', 'UTC')
    days = int(values.get('TMOD_' + prefix + '_DAYS', '7'))
    weekday = values.get('TMOD_' + prefix + '_WEEKDAY', 'sunday')
    monthday = int(values.get('TMOD_' + prefix + '_MONTHDAY', '1'))
    settings.validate({'TMOD_RESTART_MODE': mode, 'TMOD_RESTART_INTERVAL': str(interval // 60),
                       'TMOD_RESTART_TIME': clock, 'TMOD_RESTART_TIMEZONE': timezone,
                       'TMOD_RESTART_DAYS': str(days), 'TMOD_RESTART_WEEKDAY': weekday,
                       'TMOD_RESTART_MONTHDAY': str(monthday)})
    calendar_mode = mode in ('daily', 'weekly', 'monthly')
    if mode == 'days':
        interval = days * 86400
    enabled = calendar_mode or (mode in ('interval', 'days') and interval > 0)
    next_at = (next_calendar(time.time(), clock, timezone, mode, weekday, monthday) if calendar_mode
               else time.time() + interval if enabled else None)
    return {
        'state': 'scheduled' if enabled else 'disabled', 'mode': mode,
        'time': clock, 'timezone': timezone, 'next_at': next_at,
        'days': days, 'weekday': weekday, 'monthday': monthday, 'interval_seconds': interval,
        'deadline': time.monotonic() + interval if mode in ('interval', 'days') and enabled else None,
        'detail': 'Waiting for the next scheduled restart.' if enabled else 'Scheduled restarts are disabled.',
    }


def reset():
    with locked():
        settings.atomic_json(settings.RUNTIME / 'restart-schedule.json', build_schedule())


@contextlib.contextmanager
def locked():
    settings.RUNTIME.mkdir(parents=True, exist_ok=True)
    with (settings.RUNTIME / 'restart-schedule.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def due():
    value = status()
    if value.get('state') != 'scheduled':
        return False
    return (time.time() >= value['next_at'] if value.get('mode') in ('daily', 'weekly', 'monthly')
            else time.monotonic() >= value['deadline'])


def record(state, detail):
    with locked():
        settings.atomic_json(settings.RUNTIME / 'restart-schedule.json',
                             {**status(), 'state': state, 'detail': detail})


def control(action, minutes=15):
    with locked():
        value = status()
        if value.get('state') not in ('scheduled', 'countdown'):
            raise ValueError('The restart can only be changed before saving and stopping begins.')
        now = time.time()
        if action == 'postpone':
            if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 1440:
                raise ValueError('Postpone by 1 through 1440 minutes.')
            seconds = minutes * 60
            next_at = max(now, value.get('next_at') or now) + seconds
            value.update(next_at=next_at, deadline=time.monotonic() + next_at - now,
                         state='scheduled', detail=f'Restart postponed by {minutes} minutes.')
        elif action == 'skip':
            if value.get('resume_schedule'):
                value = value['resume_schedule']
                value['detail'] = 'Manual restart canceled; the recurring schedule is unchanged.'
            elif value.get('mode') == 'disabled':
                value.update(state='disabled', next_at=None, deadline=None, detail='Manual restart canceled.')
            else:
                if value['mode'] in ('daily', 'weekly', 'monthly'):
                    next_at = next_calendar(max(now, value.get('next_at') or now), value['time'], value['timezone'],
                                            value['mode'], value['weekday'], value['monthday'])
                else:
                    next_at = max(now, value.get('next_at') or now) + value['interval_seconds']
                value.update(state='scheduled', next_at=next_at, deadline=time.monotonic() + next_at - now,
                             detail='One restart skipped; the next occurrence is scheduled.')
        else:
            raise ValueError('Choose postpone or skip.')
        value.pop('countdown_end', None)
        settings.atomic_json(settings.RUNTIME / 'restart-schedule.json', value)
        return value


def begin_countdown(manual=False):
    delay = int(os.environ.get('TMOD_RESTART_DELAY', '60'))
    warnings = settings.validate({'TMOD_RESTART_COUNTDOWN': os.environ.get('TMOD_RESTART_COUNTDOWN', '300,60,10')})
    settings.validate({'TMOD_RESTART_DELAY': str(delay)})
    with locked():
        if not manual and not due():
            return False
        value = status()
        if manual:
            value = {**value, 'resume_schedule': value.copy(), 'next_at': time.time()}
        value.update(state='countdown', countdown_end=time.time() + delay,
                     countdown_deadline=time.monotonic() + delay,
                     warnings=[int(part) for part in warnings['TMOD_RESTART_COUNTDOWN'].split(',') if part and int(part) <= delay],
                     detail='Restart countdown in progress. You can postpone or skip before saving starts.')
        settings.atomic_json(settings.RUNTIME / 'restart-schedule.json', value)
    return True


def countdown_step():
    with locked():
        value = status()
        if value.get('state') != 'countdown':
            return 'canceled', None
        remaining = max(0, math.ceil(value['countdown_deadline'] - time.monotonic()))
        if remaining == 0:
            value.update(state='stopping', detail='Saving and stopping the game; countdown controls are closed.')
            message = None
            outcome = 'ready'
        else:
            crossed = [seconds for seconds in value['warnings'] if seconds >= remaining]
            value['warnings'] = [seconds for seconds in value['warnings'] if seconds < remaining]
            message = f'Server restarting in {remaining} seconds.' if crossed else None
            outcome = 'waiting'
        settings.atomic_json(settings.RUNTIME / 'restart-schedule.json', value)
        return outcome, message


def announce(message):
    if message:
        try:
            subprocess.run(['inject', 'say ' + message], timeout=7, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'[RESTART] Announcement delivery failed: {error}', flush=True)


def countdown(manual=False):
    if not begin_countdown(manual):
        return 2
    announce(os.environ.get('TMOD_RESTART_MESSAGE', 'Server restarting soon.'))
    while True:
        outcome, message = countdown_step()
        announce(message)
        if outcome == 'ready':
            return 0
        if outcome == 'canceled':
            announce('Server restart postponed or skipped.')
            return 2
        time.sleep(1)


if __name__ == '__main__':
    if sys.argv[1] == 'reset':
        reset()
    elif sys.argv[1] == 'due':
        sys.exit(0 if due() else 1)
    elif sys.argv[1] == 'countdown':
        sys.exit(countdown(len(sys.argv) > 2 and sys.argv[2] == 'manual'))
    else:
        record(sys.argv[1], sys.argv[2])
