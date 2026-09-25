import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin_backup_schedule as backups
import admin_logs as logs
import admin_restart as restart
import admin_settings as settings
import console_tee


class OperationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        runtime = patch.object(settings, 'RUNTIME', self.root)
        runtime.start(); self.addCleanup(runtime.stop)

    def test_countdown_thresholds_and_stopping_boundary(self):
        with patch.dict(os.environ, {'TMOD_RESTART_DELAY': '61', 'TMOD_RESTART_COUNTDOWN': '300,60,10'}), \
                patch.object(restart.time, 'monotonic', return_value=100), patch.object(restart.time, 'time', return_value=1000):
            restart.reset()
            self.assertTrue(restart.begin_countdown(manual=True))
            self.assertEqual(restart.countdown_step(), ('waiting', None))
        for clock, message in ((101, 'Server restarting in 60 seconds.'), (102, None), (151, 'Server restarting in 10 seconds.')):
            with patch.object(restart.time, 'monotonic', return_value=clock):
                self.assertEqual(restart.countdown_step(), ('waiting', message))
        with patch.object(restart.time, 'monotonic', return_value=161):
            self.assertEqual(restart.countdown_step(), ('ready', None))
        with self.assertRaises(ValueError):
            restart.control('postpone', 5)

    def test_postpone_and_skip_cancel_without_disabling_recurring_schedule(self):
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'daily', 'TMOD_RESTART_TIME': '04:00', 'TMOD_RESTART_TIMEZONE': 'UTC'}), \
                patch.object(restart.time, 'time', return_value=14400), patch.object(restart.time, 'monotonic', return_value=100):
            restart.reset()
            self.assertTrue(restart.begin_countdown(manual=True))
            value = restart.control('postpone', 15)
            self.assertEqual(value['next_at'], 15300)
            self.assertEqual(value['mode'], 'daily')
            self.assertEqual(restart.countdown_step(), ('canceled', None))
            self.assertFalse(restart.begin_countdown())
            value = restart.control('skip')
            self.assertEqual(value['next_at'], 100800)
            self.assertEqual(value['state'], 'scheduled')
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'disabled'}):
            restart.reset()
            restart.begin_countdown(manual=True)
            self.assertEqual(restart.control('skip')['state'], 'disabled')

    def test_countdown_validation_and_zero_delay(self):
        self.assertEqual(settings.validate({'TMOD_RESTART_COUNTDOWN': '10,60,10'})['TMOD_RESTART_COUNTDOWN'], '60,10')
        for value in ('-1', '0', '3601', '10,no', '10\nexit'):
            with self.assertRaises(ValueError): settings.validate({'TMOD_RESTART_COUNTDOWN': value})
        with patch.dict(os.environ, {'TMOD_RESTART_DELAY': '0', 'TMOD_RESTART_COUNTDOWN': ''}):
            self.assertTrue(restart.begin_countdown(manual=True))
            self.assertEqual(restart.countdown_step(), ('ready', None))

    def test_future_postpone_and_manual_cancel_preserve_calendar(self):
        with patch.dict(os.environ, {'TMOD_RESTART_MODE': 'daily', 'TMOD_RESTART_TIME': '04:00', 'TMOD_RESTART_TIMEZONE': 'UTC'}), \
                patch.object(restart.time, 'time', return_value=0), patch.object(restart.time, 'monotonic', return_value=100):
            restart.reset()
            original = restart.status()['next_at']
            self.assertEqual(restart.control('postpone', 15)['next_at'], original + 900)
            restart.reset()
            restart.begin_countdown(manual=True)
            self.assertEqual(restart.control('postpone', 15)['next_at'], 900)
            self.assertEqual(restart.control('skip')['next_at'], original)

    def test_backup_schedule_independent_and_legacy_interval(self):
        with patch.dict(os.environ, {'TMOD_BACKUP_MODE': 'interval', 'TMOD_BACKUP_INTERVAL': '10', 'TMOD_RESTART_MODE': 'disabled'}), \
                patch.object(restart.time, 'time', return_value=0), patch.object(restart.time, 'monotonic', return_value=100):
            restart.reset(); backups.reset()
            self.assertFalse(restart.due()); self.assertFalse(backups.due())
            self.assertEqual(backups.status()['next_at'], 600)
        with patch.object(restart.time, 'monotonic', return_value=700):
            self.assertTrue(backups.due())
        with patch.dict(os.environ, {'TMOD_BACKUP_MODE': 'monthly', 'TMOD_BACKUP_MONTHDAY': '31',
                                     'TMOD_BACKUP_TIME': '03:00', 'TMOD_BACKUP_TIMEZONE': 'UTC'}), \
                patch.object(restart.time, 'time', return_value=0):
            backups.reset()
            self.assertEqual(backups.status()['next_at'], 30 * 86400 + 10800)
            self.assertEqual(restart.status()['state'], 'disabled')

    def test_retention_only_prunes_owned_archive_names(self):
        history = self.root / 'console-history'; history.mkdir()
        first = history / 'run-20260101T000000Z-aaaaaa.log'; first.write_bytes(b'a' * 30)
        first.with_name(first.name + '.first').write_text('timestamp')
        second = history / 'run-20260102T000000Z-bbbbbb.log'; second.write_bytes(b'b' * 30)
        third = history / 'run-20260103T000000Z-cccccc.log'; third.write_bytes(b'c' * 30)
        for path, stamp in ((first, 10), (second, 20), (third, 30)): os.utime(path, (stamp, stamp))
        protected = [self.root / 'container-console.log', self.root / 'container-console.previous.log', history / 'server.log']
        for path in protected: path.write_text('keep')
        link = history / 'run-20260101T000000Z-dddddd.log'; link.symlink_to(protected[0])
        with patch.object(logs, 'limits', return_value=(15, 35, 64)):
            logs.prune(self.root, now=35)
        self.assertFalse(first.exists()); self.assertFalse(second.exists()); self.assertTrue(third.exists())
        self.assertFalse(first.with_name(first.name + '.first').exists())
        for path in protected: self.assertEqual(path.read_text(), 'keep')
        self.assertTrue(link.is_symlink())

    def test_rotation_preserves_stream_and_tracking(self):
        class Chunks:
            def __init__(self): self.chunks = iter((b'first\n', b'second\n', b'third\n'))
            def read1(self, size): return next(self.chunks, b'')
        target = self.root / 'container-console.log'; destination = io.BytesIO()
        with patch.object(logs, 'limits', return_value=(0, 0, 10)):
            console_tee.copy_output(Chunks(), target, destination)
        self.assertEqual(destination.getvalue(), b'first\nsecond\nthird\n')
        self.assertEqual(target.read_bytes(), b'third\n')
        self.assertEqual(sorted(path.read_bytes() for path in (self.root / 'console-history').glob('*.log')), [b'first\n', b'second\n'])
        self.assertTrue(target.with_name(target.name + '.first').exists())


if __name__ == '__main__': unittest.main()
