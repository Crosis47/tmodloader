import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.data / 'world.wld').write_bytes(b'original world')
        self.dest = self.root / 'backups'
        self.dest.mkdir()
        self.info = {'Image': 'sha256:test', 'Config': {'Image': 'image:test'},
                     'State': {'Running': True}}
        self.args = types.SimpleNamespace(container='test', stop_timeout=120, health_timeout=600)

    def bundle(self):
        return backup.create_backup(self.data, self.dest, self.info)

    def test_round_trip_and_original_preserved(self):
        bundle = self.bundle()
        (self.data / 'world.wld').write_bytes(b'new world')
        with patch.object(backup, 'stop'), patch.object(backup, 'docker'), patch.object(backup, 'wait_healthy') as health:
            backup.restore(bundle, self.data, self.info, self.args)
        self.assertEqual((self.data / 'world.wld').read_bytes(), b'original world')
        old = next(self.root.glob('data.before-restore-*'))
        self.assertEqual((old / 'world.wld').read_bytes(), b'new world')
        health.assert_called_once()

    def test_corruption_rejected_before_stop(self):
        bundle = self.bundle()
        with (bundle / 'data.tar.gz').open('ab') as stream:
            stream.write(b'corruption')
        with patch.object(backup, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                backup.restore(bundle, self.data, self.info, self.args)
        stop.assert_not_called()

    def test_unsafe_members_rejected_even_with_valid_checksum(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('data/link', tarfile.SYMTYPE), ('data/hard', tarfile.LNKTYPE),
                           ('data/fifo', tarfile.FIFOTYPE)]:
            with self.subTest(name=name):
                bundle = self.bundle()
                with tarfile.open(bundle / 'data.tar.gz', 'w:gz') as tar:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = '/etc/passwd' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
                    tar.addfile(entry, io.BytesIO(b''))
                manifest = json.loads((bundle / 'manifest.json').read_text())
                manifest['sha256'] = backup.digest(bundle / 'data.tar.gz')
                (bundle / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    backup.validate(bundle)

    def test_wrong_image_rejected_before_stop(self):
        bundle = self.bundle()
        self.info['Image'] = 'different'
        with patch.object(backup, 'stop') as stop:
            with self.assertRaisesRegex(ValueError, 'image differs'):
                backup.restore(bundle, self.data, self.info, self.args)
        stop.assert_not_called()

    def test_failed_health_preserves_both_trees(self):
        bundle = self.bundle()
        (self.data / 'world.wld').write_bytes(b'new world')
        with patch.object(backup, 'stop'), patch.object(backup, 'docker') as docker, patch.object(backup, 'wait_healthy', side_effect=RuntimeError('bad health')):
            with self.assertRaisesRegex(RuntimeError, 'Original data remains'):
                backup.restore(bundle, self.data, self.info, self.args)
        docker.assert_any_call('stop', '--time', '120', 'test')
        self.assertEqual((self.data / 'world.wld').read_bytes(), b'original world')
        self.assertEqual(len(list(self.root.glob('data.before-restore-*'))), 1)

    def test_retention_preserves_unknown_files(self):
        bundles = [self.bundle() for _ in range(3)]
        unknown = self.dest / 'tmod-backup-unknown'
        unknown.mkdir()
        backup.retain(self.dest, 1, bundles[-1])
        self.assertTrue(bundles[-1].exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(len([p for p in self.dest.iterdir() if p != unknown]), 1)

    def test_backup_failure_restarts_without_retention(self):
        with patch.object(backup, 'stop'), patch.object(backup, 'docker') as docker, patch.object(backup, 'wait_healthy'), patch.object(backup, 'create_backup', side_effect=OSError('disk full')), patch.object(backup, 'retain') as retain:
            with self.assertRaisesRegex(OSError, 'disk full'):
                backup.run_backup(self.data, self.dest, self.info, self.args)
        docker.assert_called_once_with('start', 'test')
        retain.assert_not_called()

    def test_lock_excludes_second_operation(self):
        with backup.lock(self.data):
            with self.assertRaisesRegex(RuntimeError, 'lock exists'):
                with backup.lock(self.data):
                    self.fail('Second lock acquired')

    def test_stopped_restore_does_not_start_container(self):
        bundle = self.bundle()
        self.info['State']['Running'] = False
        with patch.object(backup, 'docker') as docker:
            backup.restore(bundle, self.data, self.info, self.args)
        docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
