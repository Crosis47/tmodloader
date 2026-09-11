from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import create_world


class WorldCreationTests(unittest.TestCase):
    def test_launcher_propagates_server_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config'
            config.write_text('')
            result = subprocess.run([sys.executable, create_world.__file__, str(config),
                                     sys.executable, '-c', 'raise SystemExit(42)'])
            self.assertEqual(result.returncode, 42)

    def test_creation_maps_options_and_requires_saved_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / 'server.py'
            fake.write_text('''
import pathlib, sys, os
sys.stdin.reconfigure(encoding='utf-16-le' if os.name == 'nt' else 'utf-8')
config = pathlib.Path(sys.argv[sys.argv.index('-config') + 1]).read_text()
assert 'language=en-US' in config and 'world=' not in config and 'autocreate=' not in config
assert 'modpack=Example' in config
for prompt, expected in [('Choose World:', 'n'), ('Choose size:', '2'),
                         ('Choose difficulty:', '3'), ('Choose world evil:', sys.argv[1]),
                         ('Enter world name:', 'Test'), ('Enter Seed (Leave Blank For Random):', '123')]:
    print(prompt, end='', flush=True)
    assert input() == expected
if sys.argv[2] != 'missing':
    pathlib.Path(sys.argv[2]).write_bytes(b'saved-world')
print('Choose World:', end='', flush=True)
input()
''')
            config = root / 'config'
            world = root / 'Test.wld'
            for evil, menu in [('corruption', '2'), ('crimson', '3')]:
                config.write_text(f'# tmod-worldevil={evil}\nworld={world}\nworldname=Test\n'
                                  'autocreate=2\ndifficulty=2\nseed=123\nmodpack=Example\n')
                create_world.create(config, [sys.executable, str(fake), menu, str(world), '-config', str(config)])
                self.assertEqual(world.read_bytes(), b'saved-world')
                world.unlink()
            with self.assertRaisesRegex(RuntimeError, 'without saving expected world'):
                create_world.create(config, [sys.executable, str(fake), '3', 'missing', '-config', str(config)])

    def test_existing_world_and_unmarked_config_do_not_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'config'
            config.write_text('world=absent.wld\n')
            with patch.object(subprocess, 'Popen') as spawn:
                create_world.create(config, [])
                world = root / 'existing.wld'
                world.write_bytes(b'unchanged')
                config.write_text(f'# tmod-worldevil=crimson\nworld={world}\n')
                create_world.create(config, [])
                spawn.assert_not_called()
                self.assertEqual(world.read_bytes(), b'unchanged')

    def test_fragmented_prompts_and_seed_step(self):
        script = """
import sys, time
for prompt, expected in [('Choose world:', 'n'), ('Choose evil:', '3'), ('Enter seed:', '123')]:
    for char in prompt:
        sys.stdout.write(char); sys.stdout.flush()
    assert input() == expected
print('Choose world:', end='', flush=True)
"""
        child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, bufsize=0)
        try:
            create_world.drive(child, [(r'Choose world:', 'n'), (r'Choose evil:', '3'),
                                       (r'Enter seed:', '123'), (r'Choose world:', None)], timeout=10)
            self.assertEqual(child.wait(timeout=5), 0)
        finally:
            if child.poll() is None:
                child.kill(); child.wait()
            child.stdin.close(); child.stdout.close()

    def test_premature_exit_fails(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, bufsize=0)
        try:
            with self.assertRaisesRegex(RuntimeError, 'exited before prompt'):
                create_world.drive(child, [(r'Choose world:', 'n')], timeout=5)
        finally:
            child.wait(timeout=5)
            child.stdin.close(); child.stdout.close()

    def test_timeout_fails(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        try:
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                create_world.drive(child, [(r'Choose world:', 'n')], timeout=0.1)
        finally:
            child.kill(); child.wait()
            child.stdin.close(); child.stdout.close()


if __name__ == '__main__':
    unittest.main()
