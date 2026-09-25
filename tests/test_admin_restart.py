import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import admin_restart as restart
import admin_settings as settings

ROOT = Path(__file__).resolve().parents[1]


class RestartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        runtime = patch.object(settings, 'RUNTIME', self.root)
        runtime.start()
        self.addCleanup(runtime.stop)

    def test_disabled_and_enabled_deadlines_and_failure_pause(self):
        self.assertFalse(restart.due())
        with patch.dict(os.environ, {'TMOD_RESTART_INTERVAL': '0'}):
            restart.reset()
        self.assertIsNone(restart.status()['next_at'])
        self.assertFalse(restart.due())
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'interval', 'TMOD_RESTART_INTERVAL': '5'}), \
                patch.object(restart.time, 'time', return_value=1000), \
                patch.object(restart.time, 'monotonic', return_value=100):
            restart.reset()
        self.assertEqual(restart.status()['next_at'], 1300)
        with patch.object(restart.time, 'monotonic', return_value=399):
            self.assertFalse(restart.due())
        with patch.object(restart.time, 'monotonic', return_value=400):
            self.assertTrue(restart.due())
            restart.record('running', 'Restarting')
            self.assertFalse(restart.due())
            restart.record('failed', 'Stopped for recovery')
            self.assertFalse(restart.due())
            with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'interval', 'TMOD_RESTART_INTERVAL': '5'}):
                restart.reset()
            self.assertFalse(restart.due())
            self.assertEqual(restart.status()['deadline'], 700)

    def test_daily_timezones_and_clock_changes(self):
        cases = [
            ('2026-09-24T07:00:00+00:00', '04:00', '2026-09-24T08:00:00+00:00'),
            ('2026-09-24T08:01:00+00:00', '04:00', '2026-09-25T08:00:00+00:00'),
            # Spring gap: 02:30 shifts to 03:30 local.
            ('2026-03-08T05:00:00+00:00', '02:30', '2026-03-08T07:30:00+00:00'),
            # Autumn fold: 01:30 fires once at its first occurrence.
            ('2026-11-01T04:00:00+00:00', '01:30', '2026-11-01T05:30:00+00:00'),
            ('2026-11-01T05:31:00+00:00', '01:30', '2026-11-02T06:30:00+00:00'),
        ]
        for now, clock, expected in cases:
            with self.subTest(now=now, clock=clock):
                self.assertEqual(restart.next_daily(datetime.fromisoformat(now).timestamp(), clock, 'America/New_York'),
                                 datetime.fromisoformat(expected).timestamp())
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'daily', 'TMOD_RESTART_TIME': '04:00',
                                     'TMOD_RESTART_TIMEZONE': 'UTC'}), \
                patch.object(restart.time, 'time', return_value=0):
            restart.reset()
            self.assertFalse(restart.due())
            self.assertEqual(restart.status()['next_at'], 14400)
        with patch.object(restart.time, 'time', return_value=14400):
            self.assertTrue(restart.due())

    def test_settings_bounds(self):
        for values in ({'TMOD_RESTART_INTERVAL': '-1'}, {'TMOD_RESTART_INTERVAL': '1.5'},
                       {'TMOD_RESTART_DELAY': '3601'}, {'TMOD_RESTART_MESSAGE': 'hello\nexit'},
                       {'TMOD_RESTART_MODE': 'yearly'}, {'TMOD_RESTART_TIME': '24:00'},
                       {'TMOD_RESTART_DAYS': '0'}, {'TMOD_RESTART_DAYS': '3651'},
                       {'TMOD_RESTART_DAYS': '1.5'}, {'TMOD_RESTART_MONTHDAY': '0'},
                       {'TMOD_RESTART_MONTHDAY': '32'}, {'TMOD_RESTART_WEEKDAY': 'someday'},
                       {'TMOD_RESTART_TIME': '4:00'}, {'TMOD_RESTART_TIMEZONE': 'invalid/timezone'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                settings.validate(values)
        self.assertEqual(settings.validate({'TMOD_RESTART_INTERVAL': '0', 'TMOD_RESTART_MESSAGE': ''}),
                         {'TMOD_RESTART_INTERVAL': '0', 'TMOD_RESTART_MESSAGE': ''})

    def test_weekly_monthly_calendar_boundaries(self):
        cases = [
            ('2026-09-24T00:00:00+00:00', 'weekly', 'thursday', 1, '2026-09-24T04:00:00+00:00'),
            ('2026-09-24T04:00:00+00:00', 'weekly', 'thursday', 1, '2026-10-01T04:00:00+00:00'),
            ('2026-12-31T05:00:00+00:00', 'weekly', 'thursday', 1, '2027-01-07T04:00:00+00:00'),
            ('2026-02-01T00:00:00+00:00', 'monthly', 'sunday', 31, '2026-02-28T04:00:00+00:00'),
            ('2028-02-01T00:00:00+00:00', 'monthly', 'sunday', 31, '2028-02-29T04:00:00+00:00'),
            ('2026-04-01T00:00:00+00:00', 'monthly', 'sunday', 31, '2026-04-30T04:00:00+00:00'),
            ('2026-04-30T04:01:00+00:00', 'monthly', 'sunday', 31, '2026-05-31T04:00:00+00:00'),
            ('2026-12-31T04:00:00+00:00', 'monthly', 'sunday', 31, '2027-01-31T04:00:00+00:00'),
        ]
        for now, mode, weekday, monthday, expected in cases:
            with self.subTest(now=now, mode=mode):
                self.assertEqual(restart.next_calendar(datetime.fromisoformat(now).timestamp(), '04:00', 'UTC',
                                                      mode, weekday, monthday), datetime.fromisoformat(expected).timestamp())

    def test_weekly_and_monthly_clock_changes(self):
        for mode, day in (('weekly', 1), ('monthly', 8)):
            self.assertEqual(restart.next_calendar(datetime.fromisoformat('2026-03-01T08:00:00+00:00').timestamp(),
                                                  '02:30', 'America/New_York', mode, 'sunday', day),
                             datetime.fromisoformat('2026-03-08T07:30:00+00:00').timestamp())
        for mode in ('weekly', 'monthly'):
            next_at = restart.next_calendar(datetime.fromisoformat('2026-11-01T05:31:00+00:00').timestamp(),
                                            '01:30', 'America/New_York', mode, 'sunday', 1)
            expected = '2026-11-08T06:30:00+00:00' if mode == 'weekly' else '2026-12-01T06:30:00+00:00'
            self.assertEqual(next_at, datetime.fromisoformat(expected).timestamp())

    def test_all_modes_reset_and_due(self):
        for mode, seconds in (('days', 3 * 86400), ('daily', 14400), ('weekly', 3 * 86400 + 14400),
                              ('monthly', 30 * 86400 + 14400)):
            with self.subTest(mode=mode), patch.dict(os.environ, {
                    'TMOD_RESTART_MODE': mode, 'TMOD_RESTART_DAYS': '3', 'TMOD_RESTART_WEEKDAY': 'sunday',
                    'TMOD_RESTART_MONTHDAY': '31', 'TMOD_RESTART_TIME': '04:00', 'TMOD_RESTART_TIMEZONE': 'UTC'}):
                with patch.object(restart.time, 'time', return_value=0), patch.object(restart.time, 'monotonic', return_value=100):
                    restart.reset()  # Epoch is Thursday, January 1, 1970.
                    self.assertEqual(restart.status()['next_at'], seconds)
                    self.assertFalse(restart.due())
                with patch.object(restart.time, 'time', return_value=seconds), \
                        patch.object(restart.time, 'monotonic', return_value=100 + seconds):
                    self.assertTrue(restart.due())
                    restart.record('failed', 'Paused')
                    self.assertFalse(restart.due())

    def test_days_use_elapsed_time_despite_wall_clock_change(self):
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'days', 'TMOD_RESTART_DAYS': '2'}), \
                patch.object(restart.time, 'time', return_value=0), \
                patch.object(restart.time, 'monotonic', return_value=100):
            restart.reset()
        with patch.object(restart.time, 'time', return_value=999999), \
                patch.object(restart.time, 'monotonic', return_value=100 + 86400):
            self.assertFalse(restart.due())
        with patch.object(restart.time, 'time', return_value=0), \
                patch.object(restart.time, 'monotonic', return_value=100 + 2 * 86400):
            self.assertTrue(restart.due())

    def test_restart_saves_then_starts_and_reports_health(self):
        source = (ROOT / 'entrypoint.sh').read_text()
        function = source[source.index('perform_scheduled_restart() {'):source.index('\nperform_runtime_update() {')]
        for healthy_exit in ('0', '1'):
            with self.subTest(healthy_exit=healthy_exit):
                harness = '''
set -Eeuo pipefail
runtime_dir="$TEST_ROOT"
pid_path="$runtime_dir/server.pid"
control_pipe="$runtime_dir/console"
exec 3<> /dev/null
bash -c "exit $TEST_GAME_EXIT" &
server_pid=$!
python3() { printf 'status:%s\n' "$2"; }
admin_progress() { printf 'progress:%s\n' "$1"; }
inject() { printf 'command:%s\n' "$1"; }
sleep() { printf 'delay:%s\n' "$1"; }
stop_autosave() { echo stop-autosave; }
server_is_running() { return 0; }
wait_for_server_exit() { return 0; }
signal_server_group() { echo terminate; }
start_server() { echo start-game; bash -c 'exit 0' & server_pid=$!; }
healthcheck() { echo check-health; return 0; }
'''
                result = subprocess.run(['bash', '-c', harness + function + '\nperform_scheduled_restart test'],
                                        env={**os.environ, 'TEST_ROOT': str(self.root), 'TEST_GAME_EXIT': healthy_exit,
                                             'TMOD_RESTART_MESSAGE': 'Restart soon', 'TMOD_RESTART_DELAY': '7',
                                             'TMOD_WEB_ENABLED': '1'}, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertLess(lines.index('status:countdown'), lines.index('command:exit'))
                status = settings.read_json(self.root / 'admin-result')
                self.assertEqual(status['status'], int(healthy_exit))
                if healthy_exit == '0':
                    self.assertLess(lines.index('command:exit'), lines.index('start-game'))
                    self.assertLess(lines.index('start-game'), lines.index('check-health'))
                else:
                    self.assertNotIn('start-game', lines)
                    self.assertIn('status:failed', lines)


if __name__ == '__main__':
    unittest.main()
