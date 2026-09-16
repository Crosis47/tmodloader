import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_settings as settings
import admin_world_time as timing
import console_tee


class UptimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for helper in [patch.object(settings, 'DATA', self.root),
                       patch.object(timing, 'process_identity', return_value='test-process'),
                       patch.object(timing.time, 'monotonic', return_value=100)]:
            result = helper.start(); self.addCleanup(helper.stop)
            self.clock = result

    def test_two_sessions_accumulate_without_counting_downtime(self):
        tracker = timing.SessionTracker('First')
        self.addCleanup(tracker.finish)
        self.assertIsNone(timing.read('First')['total_uptime_seconds'])
        tracker.start()
        self.clock.return_value = 220
        self.assertEqual(timing.read('First')['session_uptime_seconds'], 120)
        self.assertEqual(timing.read('First')['total_uptime_seconds'], 120)
        tracker.finish()
        self.clock.return_value = 1000
        self.assertIsNone(timing.read('First')['session_uptime_seconds'])
        self.assertEqual(timing.read('First')['total_uptime_seconds'], 120)
        second = timing.SessionTracker('First')
        self.addCleanup(second.finish)
        second.start()
        self.clock.return_value = 1060
        second.finish()
        self.assertEqual(timing.read('First')['total_uptime_seconds'], 180)
        self.assertIsNone(timing.read('Other')['total_uptime_seconds'])

    def test_checkpoint_survives_abrupt_exit_and_pid_reuse(self):
        tracker = timing.SessionTracker('First')
        self.addCleanup(tracker.finish)
        tracker.start()
        self.clock.return_value = 110
        tracker.checkpoint()
        self.clock.return_value = 9999
        with patch.object(timing, 'process_identity', return_value='different-process'):
            self.assertEqual(timing.read('First')['total_uptime_seconds'], 10)
            self.assertIsNone(timing.read('First')['session_uptime_seconds'])

    def test_duplicate_ready_message_does_not_reset_session(self):
        tracker = timing.SessionTracker('First')
        self.addCleanup(tracker.finish)
        tracker.start()
        self.clock.return_value = 125
        tracker.start()
        self.assertEqual(timing.read('First')['session_uptime_seconds'], 25)

    def test_console_detects_ready_across_chunks_and_preserves_output(self):
        source, tracker, output = Mock(), Mock(), io.BytesIO()
        source.read1.side_effect = [b'Loading\nSer', b'ver started\r\n', b'Ready\n', b'']
        console_tee.copy_output(source, self.root / 'log', output, tracker)
        self.assertTrue(tracker.start.called)
        self.assertEqual(output.getvalue(), b'Loading\nServer started\r\nReady\n')

    def test_loading_without_ready_does_not_start_tracking(self):
        tracker = Mock()
        console_tee.copy_output(io.BytesIO(b'Loading world\n'), self.root / 'log', io.BytesIO(), tracker)
        tracker.start.assert_not_called()
