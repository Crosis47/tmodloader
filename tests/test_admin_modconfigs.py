import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_modconfigs as configs
import admin_settings as settings
import admin_worlds as worlds


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        helper = patch.object(settings, 'DATA', Path(temporary.name))
        helper.start(); self.addCleanup(helper.stop)
        configs.directory().mkdir(parents=True)
        self.file = configs.directory() / 'Example_Server.json'
        self.file.write_text('{"Enabled": true}')

    def test_save_and_stale_revision(self):
        original = configs.read(self.file.name)
        result = configs.save({**original, 'content': '{"Enabled": false}'})
        self.assertIn('false', result['content'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            configs.save(original)

    def test_formats_validate_and_preserve_comments(self):
        examples = [
            ('custom.YAML', '# comment\nenabled: true\n', 'enabled: [', 'YAML'),
            ('custom.toml', '# comment\nenabled = true\n', 'enabled = [', 'TOML'),
            ('custom.ini', '; comment\n[main]\nEnabled = yes\n', '[main', 'INI'),
            ('custom.xml', '<!-- comment --><config enabled="true"/>', '<config>', 'XML'),
            ('custom.cfg', 'custom syntax!\n', None, 'Text'),
        ]
        for name, valid, invalid, kind in examples:
            with self.subTest(name=name):
                path = configs.directory() / name
                path.write_text(valid)
                current = configs.read(name)
                self.assertEqual(current['format'], kind)
                self.assertIn(name, configs.inventory()['files'])
                configs.save({**current, 'content': valid})
                self.assertEqual(path.read_bytes(), valid.encode())
                if invalid:
                    with self.assertRaisesRegex(ValueError, 'Invalid ' + kind):
                        configs.save({**configs.read(name), 'content': invalid})
                    self.assertEqual(path.read_bytes(), valid.encode())

    def test_binary_and_unsafe_serialization_rejected(self):
        (configs.directory() / 'binary.dat').write_bytes(b'\x00\xff')
        with self.assertRaises(ValueError):
            configs.read('binary.dat')
        for name, content in [('config.yaml', '!!python/object:os.system {}'),
                              ('config.xml', '<!DOCTYPE config><config/>')]:
            with self.assertRaises(ValueError):
                configs.validate_content(name, content)

    def test_invalid_json_and_paths_preserve_file(self):
        original = self.file.read_text()
        for content in ('{broken', '[]', '{"value": NaN}'):
            with self.assertRaises(ValueError):
                configs.save({**configs.read(self.file.name), 'content': content})
        for name in ('../outside.json', 'C:outside.json', 'missing.json'):
            with self.assertRaises(ValueError):
                configs.read(name)
        self.assertEqual(self.file.read_text(), original)

    def test_world_delete_protects_running_and_staged(self):
        worlds.directory().mkdir()
        current = {'running': {'TMOD_WORLDNAME': 'Active'}, 'staged': {'TMOD_WORLDNAME': 'Draft'}}
        with patch.dict(os.environ, {'TMOD_USECONFIGFILE': 'No'}):
            for name in ('Active', 'Draft'):
                with self.assertRaisesRegex(ValueError, 'Cannot delete'):
                    worlds.delete(name, current)
            for suffix in ('.wld', '.twld', '.wld.bak', '.twld.bak2'):
                (worlds.directory() / ('Old' + suffix)).write_bytes(b'data')
            worlds.delete('Old', current)
            self.assertEqual(list(worlds.directory().iterdir()), [])
