"""Exercise scheduled commands and shutdown ordering without a live game."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import admin_settings as settings


class RuntimeControlsTests(unittest.TestCase):
    def test_settings_validation(self):
        self.assertEqual(settings.validate({'TMOD_AUTOSAVE_MESSAGE': '', 'TMOD_SHUTDOWN_DELAY': '0'}),
                         {'TMOD_AUTOSAVE_MESSAGE': '', 'TMOD_SHUTDOWN_DELAY': '0'})
        for values in ({'TMOD_AUTOSAVE_MESSAGE': 'hello\nexit'},
                       {'TMOD_SHUTDOWN_DELAY': '-1'}, {'TMOD_SHUTDOWN_DELAY': '3601'},
                       {'TMOD_SHUTDOWN_DELAY': '1.5'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                settings.validate(values)

    def test_autosave_commands_and_interval(self):
        for message, expected in ((None, ['say Scheduled world save starting.', 'save']),
                                  ('Saving soon!', ['say Saving soon!', 'save']), ('', ['save'])):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, script in {
                    'sleep': '#!/bin/bash\necho "$1" >> "$TEST_ROOT/waits"\nif [[ -e "$TEST_ROOT/ticked" ]]; then exit 1; fi\ntouch "$TEST_ROOT/ticked"\n',
                    'inject': '#!/bin/bash\necho "$1" >> "$TEST_ROOT/commands"\n[[ "$1" != say* ]]\n',
                }.items():
                    path = root / name
                    path.write_text(script)
                    path.chmod(0o755)
                env = {**os.environ, 'PATH': directory + ':' + os.environ['PATH'],
                       'TEST_ROOT': directory, 'TMOD_AUTOSAVE_INTERVAL': '5'}
                env.pop('TMOD_AUTOSAVE_MESSAGE', None)
                if message is not None:
                    env['TMOD_AUTOSAVE_MESSAGE'] = message
                subprocess.run(['bash', str(ROOT / 'autosave.sh')], env=env, check=True,
                               capture_output=True, timeout=5)
                self.assertEqual((root / 'commands').read_text().splitlines(), expected)
                self.assertEqual((root / 'waits').read_text().splitlines(), ['5m', '5m'])

    def test_shutdown_warning_precedes_save_and_exit(self):
        source = (ROOT / 'entrypoint.sh').read_text()
        shutdown = source[source.index('shutdown() {'):source.index('\ncleanup() {')]
        for delay in ('0', '7'):
            with self.subTest(delay=delay):
                harness = '''
set -eu
shutdown_requested=0
countdown_pid=''
server_pid=999999
stop_autosave() { echo stop-autosave; }
server_is_running() { return 0; }
inject() { echo "command:$1"; }
sleep() { echo "delay:$1"; }
wait_for_server_exit() { echo wait-for-exit; return 0; }
'''
                result = subprocess.run(['bash', '-c', harness + shutdown + '\nshutdown'],
                                        env={**os.environ, 'TMOD_SHUTDOWN_DELAY': delay,
                                             'TMOD_SHUTDOWN_MESSAGE': 'Stopping soon'},
                                        text=True, capture_output=True, check=True, timeout=5)
                self.assertEqual(result.stdout.splitlines(),
                                 ['stop-autosave', 'command:say Stopping soon', 'delay:' + delay,
                                  'command:exit', 'wait-for-exit'])


if __name__ == '__main__':
    unittest.main()
