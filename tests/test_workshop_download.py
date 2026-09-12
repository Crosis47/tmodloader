import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import workshop_download


class NativeDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / '123'
        self.target.mkdir()
        (self.target / 'old.tmod').write_bytes(b'TMODold')

    def downloader(self, args, **kwargs):
        destination = Path(args[args.index('-dir') + 1])
        destination.mkdir()
        (destination / 'new.tmod').write_bytes(b'TMODnew')
        return subprocess.CompletedProcess(args, 0, 'Total downloaded: 7 bytes from 1 depots\n')

    def test_success_replaces_cache_and_records_exact_manifest(self):
        with patch('workshop_download.subprocess.run', side_effect=self.downloader) as run:
            workshop_download.download(self.root, '123', '456', '789', 'native-tool')
        self.assertEqual(run.call_args.args[0][:5], ['native-tool', '-app', '1281930', '-ugc', '456'])
        self.assertFalse((self.target / 'old.tmod').exists())
        self.assertEqual((self.target / 'new.tmod').read_bytes(), b'TMODnew')
        state = json.loads((self.target / '.tmodloader-download.json').read_text())
        self.assertEqual(state, {'manifest': '456', 'timeupdated': '789'})
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_missing_metadata_uses_published_id_without_claiming_manifest(self):
        with patch('workshop_download.subprocess.run', side_effect=self.downloader) as run:
            workshop_download.download(self.root, '123', '', '')
        self.assertEqual(run.call_args.args[0][3:5], ['-pubfile', '123'])
        state = json.loads((self.target / '.tmodloader-download.json').read_text())
        self.assertEqual(state['manifest'], '')

    def test_nonzero_exit_preserves_cache(self):
        with patch('workshop_download.subprocess.run', return_value=subprocess.CompletedProcess([], 1, 'failed')):
            with self.assertRaises(subprocess.CalledProcessError):
                workshop_download.download(self.root, '123', '456', '789')
        self.assertEqual((self.target / 'old.tmod').read_bytes(), b'TMODold')
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_zero_exit_without_completion_preserves_cache(self):
        def incomplete(args, **kwargs):
            self.downloader(args)
            return subprocess.CompletedProcess(args, 0, 'Unable to download manifest')
        with patch('workshop_download.subprocess.run', side_effect=incomplete):
            with self.assertRaises(RuntimeError):
                workshop_download.download(self.root, '123', '456', '789')
        self.assertTrue((self.target / 'old.tmod').exists())

    def test_success_message_without_mods_is_rejected(self):
        result = subprocess.CompletedProcess([], 0, 'Total downloaded: 0 bytes from 1 depots\n')
        with patch('workshop_download.subprocess.run', return_value=result):
            with self.assertRaises(RuntimeError):
                workshop_download.download(self.root, '123', '456', '789')
        self.assertTrue((self.target / 'old.tmod').exists())

    def test_invalid_mod_is_rejected(self):
        def invalid(args, **kwargs):
            result = self.downloader(args)
            destination = Path(args[args.index('-dir') + 1])
            (destination / 'new.tmod').write_bytes(b'partial')
            return result
        with patch('workshop_download.subprocess.run', side_effect=invalid):
            with self.assertRaises(RuntimeError):
                workshop_download.download(self.root, '123', '456', '789')
        self.assertTrue((self.target / 'old.tmod').exists())

    def test_failed_install_restores_previous_directory(self):
        replace = workshop_download.os.replace
        def fail_install(source, destination):
            if Path(source).name == 'content':
                raise OSError('Cannot install')
            return replace(source, destination)
        with patch('workshop_download.subprocess.run', side_effect=self.downloader):
            with patch('workshop_download.os.replace', side_effect=fail_install):
                with self.assertRaises(OSError):
                    workshop_download.download(self.root, '123', '456', '789')
        self.assertTrue((self.target / 'old.tmod').exists())

    def test_invalid_id_is_rejected_before_downloading(self):
        with patch('workshop_download.subprocess.run') as run:
            with self.assertRaises(ValueError):
                workshop_download.download(self.root, '../123', '456', '789')
        run.assert_not_called()

    def test_failed_rollback_keeps_recovery_files(self):
        replace = workshop_download.os.replace
        def fail_install_and_rollback(source, destination):
            if Path(destination) == self.target:
                raise OSError('Cannot restore target')
            return replace(source, destination)
        with patch('workshop_download.subprocess.run', side_effect=self.downloader):
            with patch('workshop_download.os.replace', side_effect=fail_install_and_rollback):
                with self.assertRaisesRegex(RuntimeError, 'preserved for recovery'):
                    workshop_download.download(self.root, '123', '456', '789')
        recovery = list(self.root.glob('.previous-123-*'))
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0] / 'old.tmod').read_bytes(), b'TMODold')


if __name__ == '__main__':
    unittest.main()
