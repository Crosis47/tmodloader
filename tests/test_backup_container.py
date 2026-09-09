import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch

if sys.platform != 'linux':
    raise unittest.SkipTest('Container filesystem locks require Linux')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('container_backup', ROOT / 'container-backup.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContainerBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.data, self.dest, self.runtime = [root / p for p in ('data', 'backups', 'runtime')]
        for p in (self.data, self.dest, self.runtime):
            p.mkdir()
        self.control = self.data / '.tmod-control'
        self.control.mkdir()
        for name, value in [('DATA', self.data), ('DEST', self.dest), ('CONTROL', self.control), ('RUNTIME', self.runtime)]:
            helper = patch.object(module, name, value)
            helper.start()
            self.addCleanup(helper.stop)
        for helper in (patch.object(module, 'preflight'), patch.object(module, 'identity', return_value='test-build')):
            helper.start()
            self.addCleanup(helper.stop)
        (self.data / 'world.wld').write_text('original')

    def test_roundtrip_preserves_original_and_excludes_control(self):
        bundle = module.cold_backup()
        with tarfile.open(bundle / 'data.tar.gz') as archive:
            self.assertFalse(any('.tmod-control' in m.name for m in archive))
        (self.data / 'world.wld').write_text('changed')
        module.restore(bundle)
        self.assertEqual((self.data / 'world.wld').read_text(), 'original')
        previous = next(self.control.glob('before-restore-*'))
        self.assertEqual((previous / 'world.wld').read_text(), 'changed')
        self.assertEqual((self.data / 'world.wld').stat().st_uid, os.getuid())
        self.assertFalse((self.control / 'restore-pending').exists())

    def test_live_lock_blocks_restore(self):
        bundle = module.cold_backup()
        with module.exclusive(self.control / 'server.lock'):
            with self.assertRaisesRegex(RuntimeError, 'Data is in use'):
                module.restore(bundle)

    def test_interrupted_restore_blocks_retry(self):
        bundle = module.cold_backup()
        (self.control / 'restore-pending').write_text('pending')
        with self.assertRaisesRegex(RuntimeError, 'interrupted restore'):
            module.restore(bundle)

    def test_running_server_blocks_internal_archive(self):
        (self.runtime / 'server.pid').write_text('123')
        with self.assertRaisesRegex(RuntimeError, 'server is running'):
            module.cold_backup()

    def test_fingerprint_mismatch_leaves_original(self):
        bundle = module.cold_backup()
        with patch.object(module, 'identity', return_value='different'):
            with self.assertRaisesRegex(ValueError, 'fingerprint differs'):
                module.restore(bundle)
        self.assertEqual((self.data / 'world.wld').read_text(), 'original')

    def test_interrupted_move_retains_marker_and_original(self):
        bundle = module.cold_backup()
        original_rename = Path.rename
        def fail_install(path, target):
            if 'restore-stage-' in str(path):
                raise OSError('simulated move failure')
            return original_rename(path, target)
        with patch.object(Path, 'rename', fail_install):
            with self.assertRaisesRegex(OSError, 'simulated'):
                module.restore(bundle)
        self.assertTrue((self.control / 'restore-pending').exists())
        original = next(self.control.glob('before-restore-*'))
        self.assertEqual((original / 'world.wld').read_text(), 'original')
