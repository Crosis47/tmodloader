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
        (configs.directory() / 'ModConfigs').mkdir(parents=True)
        self.file = configs.directory() / 'ModConfigs/Example_Server.json'
        self.file.write_text('{"Enabled": true}')

    def test_large_config_round_trip_and_byte_limit(self):
        import json
        content = json.dumps({'large': 'x' * (1024 * 1024)})
        self.file.write_bytes(content.encode())
        current = configs.read('ModConfigs/' + self.file.name)
        updated = content.replace('xxx', 'yyy', 1)
        self.assertEqual(configs.save({**current, 'content': updated})['content'], updated)
        exact = configs.directory() / 'ModConfigs/large.txt'
        exact.write_bytes(b'x' * configs.LIMIT)
        self.assertEqual(len(configs.read('ModConfigs/' + exact.name)['content']), configs.LIMIT)
        with self.assertRaisesRegex(ValueError, '4 MiB'):
            configs.validate_content('ModConfigs/' + exact.name, 'x' * (configs.LIMIT + 1))
        with exact.open('ab') as stream:
            stream.write(b'x')
        with self.assertRaisesRegex(ValueError, 'mounted data storage'):
            configs.read('ModConfigs/' + exact.name)
        self.assertEqual(exact.stat().st_size, configs.LIMIT + 1)

    def test_save_and_stale_revision(self):
        original = configs.read('ModConfigs/' + self.file.name)
        result = configs.save({**original, 'content': '{"Enabled": false}'})
        self.assertIn('false', result['content'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            configs.save(original)

    def test_preview_does_not_write_and_reports_conflict(self):
        original = configs.read('ModConfigs/' + self.file.name)
        preview = configs.preview({**original, 'content': '{"Enabled": false}'})
        self.assertFalse(preview['conflict'])
        self.assertIn('-{"Enabled": true}', preview['diff'])
        self.assertIn('+{"Enabled": false}', preview['diff'])
        self.assertEqual(self.file.read_text(), original['content'])
        self.assertFalse(configs.history_path(original['name']).exists())
        self.file.write_text('{"external": true}')
        with self.assertRaisesRegex(ValueError, 'Invalid JSON'):
            configs.preview({**original, 'content': '{unfinished draft'})
        preview = configs.preview({**original, 'content': '{"mine": true}'})
        self.assertTrue(preview['conflict'])
        self.assertEqual(preview['current']['content'], '{"external": true}')
        self.assertEqual(preview['content'], '{"mine": true}')
        with self.assertRaises(configs.ConflictError) as error:
            configs.save({**original, 'content': '{"mine": true}'})
        self.assertEqual(error.exception.current['content'], '{"external": true}')

    def test_undo_restores_exact_bytes_and_keeps_replaced_version(self):
        raw = b'\xef\xbb\xbf{\r\n  "Enabled": true\r\n}\r\n'
        self.file.write_bytes(raw)
        name = 'ModConfigs/' + self.file.name
        original = configs.read(name)
        saved = configs.save({**original, 'content': '{"Enabled": false}'})
        self.assertTrue(saved['can_restore'])
        review = configs.preview({**saved, 'action': 'restore'})
        self.assertEqual(review['content'], raw.decode('utf-8-sig'))
        self.assertEqual(self.file.read_text(), '{"Enabled": false}')
        restored = configs.restore({'name': name, 'revision': saved['revision'],
                                   'history_revision': review['history_revision'], 'confirm': True})
        self.assertEqual(self.file.read_bytes(), raw)
        self.assertEqual(configs.previous(name)['content'], '{"Enabled": false}')
        self.assertTrue(restored['can_restore'])
        self.assertNotIn('admin', '\n'.join(configs.inventory()['files']))

    def test_undo_needs_confirmation_and_current_history_and_file(self):
        current = configs.read('ModConfigs/' + self.file.name)
        saved = configs.save({**current, 'content': '{"saved": 1}'})
        review = configs.preview({**saved, 'action': 'restore'})
        payload = {'name': saved['name'], 'revision': saved['revision'],
                   'history_revision': review['history_revision'], 'confirm': True}
        with self.assertRaisesRegex(ValueError, 'confirm'):
            configs.restore({**payload, 'confirm': False})
        with self.assertRaisesRegex(ValueError, 'previous version changed'):
            configs.restore({**payload, 'history_revision': 'stale'})
        self.file.write_text('{"external": 2}')
        with self.assertRaises(configs.ConflictError):
            configs.restore(payload)
        self.assertEqual(self.file.read_text(), '{"external": 2}')

    def test_noop_save_preserves_history_and_line_endings(self):
        self.file.write_bytes(b'{\r\n  "Enabled": true\r\n}\r\n')
        current = configs.read('ModConfigs/' + self.file.name)
        saved = configs.save({**current, 'content': current['content'].replace('\r\n', '\n')})
        self.assertEqual(saved['revision'], current['revision'])
        self.assertFalse(saved['can_restore'])

    def test_history_is_per_file_and_survives_another_read(self):
        name = 'ModConfigs/' + self.file.name
        current = configs.read(name)
        configs.save({**current, 'content': '{"first": true}'})
        other = configs.directory() / 'other.json'
        other.write_text('{"other": true}')
        configs.save({**configs.read('other.json'), 'content': '{"other": false}'})
        self.assertEqual(configs.previous(name)['content'], '{"Enabled": true}')
        self.assertEqual(configs.previous('other.json')['content'], '{"other": true}')
        self.assertTrue(configs.read(name)['can_restore'])
        with self.assertRaisesRegex(ValueError, 'No previous'):
            untouched = configs.directory() / 'untouched.json'
            untouched.write_text('{}')
            configs.previous('untouched.json')

    def test_corrupt_or_linked_history_cannot_restore(self):
        current = configs.read('ModConfigs/' + self.file.name)
        saved = configs.save({**current, 'content': '{"saved": true}'})
        history = configs.history_path(current['name'])
        history.write_text('{corrupt')
        with self.assertRaisesRegex(ValueError, 'damaged'):
            configs.preview({**saved, 'action': 'restore'})
        self.assertEqual(self.file.read_text(), '{"saved": true}')
        history.unlink()
        outside = settings.DATA / 'outside-history'
        outside.write_text('{}')
        try:
            history.symlink_to(outside)
        except OSError:
            self.skipTest('Symbolic links unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'Linked'):
            configs.read(current['name'])

    def test_failed_write_preserves_file_and_prior_history(self):
        current = configs.read('ModConfigs/' + self.file.name)
        saved = configs.save({**current, 'content': '{"saved": true}'})
        old_history = configs.history_path(saved['name']).read_bytes()
        replace = configs.os.replace
        def fail_config(source, target):
            if Path(target) == self.file:
                raise OSError('disk full')
            replace(source, target)
        with patch.object(configs.os, 'replace', side_effect=fail_config), self.assertRaisesRegex(OSError, 'disk full'):
            configs.save({**saved, 'content': '{"changed": true}'})
        self.assertEqual(self.file.read_text(), saved['content'])
        self.assertEqual(configs.history_path(saved['name']).read_bytes(), old_history)

    def test_large_preview_uses_complete_panes_instead_of_line_diff(self):
        result = configs.change_preview('x' * (128 * 1024 + 1), 'changed')
        self.assertIsNone(result['diff'])
        self.assertTrue(result['diff_limited'])
        self.assertTrue(configs.change_preview('a\n' * 2001, 'b\n')['diff_limited'])

    def test_three_way_merge_combines_separate_edits_and_keeps_shared_edits_once(self):
        result = configs.combine_edits('a\nb\nc\nd\n', 'A\nb\nc\nd\n', 'a\nb\nc\nD\n')
        self.assertEqual(result['content'], 'A\nb\nc\nD\n')
        self.assertEqual(result['conflicts'], 0)
        result = configs.combine_edits('a\nb\nc\n', 'A\nb\nc\n', 'A\nb\nC\n')
        self.assertEqual(result['content'], 'A\nb\nC\n')
        self.assertEqual(result['conflicts'], 0)
        result = configs.combine_edits('a\nb\n', 'added\na\nb\n', 'A\nb\n')
        self.assertEqual(result['content'], 'added\nA\nb\n')
        self.assertEqual(result['conflicts'], 0)

    def test_merge_handles_unchanged_sides_and_windows_line_endings(self):
        for base, draft, disk, expected in [('a', 'a', 'b', 'b'), ('a', 'b', 'a', 'b'),
                                            ('a', 'b', 'b', 'b'),
                                            ('a\r\nb\r\n', 'A\nb\n', 'a\nb\n', 'A\nb\n')]:
            with self.subTest(base=base, draft=draft, disk=disk):
                self.assertEqual(configs.combine_edits(base, draft, disk)['content'], expected)

    def test_merge_offers_choices_for_overlapping_changes_without_markers(self):
        for base, draft, disk in [('a\nb\n', 'a\nmy edit\n', 'a\ndisk edit\n'),
                                 ('a\nb\n', 'a\n', 'a\ndisk edit\n'),
                                 ('a\n', 'added by me\na\n', 'added on disk\na\n')]:
            with self.subTest(draft=draft, disk=disk):
                result = configs.combine_edits(base, draft, disk)
                self.assertEqual(result['conflicts'], 1)
                self.assertEqual(result['unresolved'], 1)
                self.assertNotIn('<<<<<<<', result['content'])
                for value in ('my edit', 'disk edit', 'added by me', 'added on disk'):
                    if value in draft or value in disk:
                        self.assertIn(value, result['choices'][0]['mine'] + result['choices'][0]['disk'])
                resolved = configs.combine_edits(base, draft, disk, selections={'0': 'mine'})
                self.assertEqual(resolved['content'], draft)
                self.assertEqual(resolved['unresolved'], 0)

    def test_json_merge_skips_matching_settings_and_keeps_other_disk_changes(self):
        base = '{"a":1,"b":1,"c":1}'
        draft = '{"a":2,"b":2,"c":1}'
        disk = '{\n  "c": 3, "b": 1, "a": 2\n}'
        result = configs.combine_edits(base, draft, disk, 'example.json')
        self.assertEqual(configs.json.loads(result['content']), {'a': 2, 'b': 2, 'c': 3})
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['choices'], [])
        result = configs.combine_edits(base, '{"a":2,"b":1,"c":1}', disk, 'example.json')
        self.assertEqual(result['content'], disk)
        self.assertEqual(result['choices'], [])

    def test_json_merge_only_asks_about_settings_that_differ(self):
        base = '{"a":1,"b":1}'
        draft = '{"a":2,"b":2}'
        disk = '{"b": 3, "a": 2}'
        result = configs.combine_edits(base, draft, disk, 'example.json')
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(len(result['choices']), 1)
        self.assertEqual(result['choices'][0]['label'], 'Setting /b')
        self.assertEqual(result['choices'][0]['mine'], '2')
        self.assertEqual(result['choices'][0]['disk'], '3')
        result = configs.combine_edits(base, draft, disk, 'example.json', {'0': 'mine'})
        self.assertEqual(configs.json.loads(result['content']), {'a': 2, 'b': 2})
        self.assertEqual(result['unresolved'], 0)
        self.assertEqual(configs.combine_edits(base, draft, disk, 'example.json', {'0': 'disk'})['content'], disk)

    def test_json_merge_handles_nested_removals_arrays_and_value_types(self):
        base = '{"nested":{"removed":1,"value":1},"array":[1,2],"flag":false}'
        draft = '{"nested":{"value":2},"array":[2,1],"flag":true}'
        disk = '{"nested":{"removed":3,"value":2},"array":[3,2],"flag":1}'
        result = configs.combine_edits(base, draft, disk, 'example.json')
        self.assertEqual([choice['label'] for choice in result['choices']], ['Setting /nested/removed', 'Setting /array', 'Setting /flag'])
        self.assertEqual(result['choices'][0]['mine'], '(Removed)')
        resolved = configs.combine_edits(base, draft, disk, 'example.json', {'0':'mine','1':'disk','2':'mine'})
        self.assertEqual(configs.json.loads(resolved['content']), {'nested': {'value':2},'array':[3,2],'flag':True})
        self.assertEqual(resolved['unresolved'], 0)

    def test_invalid_json_never_falls_back_to_text_merging(self):
        cases = [('{}', '{"added":false}', '{"original":true "added":true}', 'Disk version'),
                 ('{}', '{"added":false}', '{"added":true,"added":false}', 'Disk version'),
                 ('{}', '{"added":false "other":1}', '{"added":true}', 'Your draft'),
                 ('{"invalid":}', '{"added":false}', '{"added":true}', 'Originally loaded version'),
                 ('{}', '{"added":false}', '[]', 'Disk version')]
        for base, draft, disk, label in cases:
            with self.subTest(disk=disk, label=label), self.assertRaisesRegex(ValueError, label + ' is not valid JSON'):
                configs.combine_edits(base, draft, disk, 'example.json')

    def test_new_json_setting_added_differently_requires_one_choice(self):
        result = configs.combine_edits('{}', '{"added":false}', '{"added":true}', 'example.json')
        self.assertEqual(len(result['choices']), 1)
        self.assertEqual(result['choices'][0]['label'], 'Setting /added')
        self.assertEqual(result['choices'][0]['mine'], 'false')
        self.assertEqual(result['choices'][0]['disk'], 'true')
        resolved = configs.combine_edits('{}', '{"added":false}', '{"added":true}', 'example.json', {'0':'mine'})
        self.assertEqual(resolved['content'].count('"added"'), 1)
        self.assertEqual(configs.json.loads(resolved['content']), {'added':False})

    def test_duplicate_json_settings_are_rejected_on_check_and_save(self):
        duplicate = '{"added":false,"added":true}'
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            configs.validate_content('example.json', duplicate)
        current = configs.read('ModConfigs/' + self.file.name)
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            configs.save({**current, 'content': duplicate})
        self.assertEqual(self.file.read_text(), current['content'])

    def test_invalid_disk_during_merge_preserves_file_and_history(self):
        name = 'ModConfigs/' + self.file.name
        old = configs.read(name)
        saved = configs.save({**old, 'content':'{"original":true}'})
        history = configs.history_path(name).read_bytes()
        malformed = '{"original":true "added":true}'
        self.file.write_text(malformed)
        current = configs.read(name)
        with self.assertRaisesRegex(ValueError, 'Disk version is not valid JSON'):
            configs.merge({'name':name,'revision':current['revision'],'base_content':saved['content'],'content':'{"original":true,"added":false}'})
        self.assertEqual(self.file.read_text(), malformed)
        self.assertEqual(configs.history_path(name).read_bytes(), history)

    def test_disk_syntax_can_be_repaired_for_combination_without_writing(self):
        name = 'ModConfigs/' + self.file.name
        base = configs.read(name)
        malformed = '{"Enabled":true "added":true}'
        self.file.write_text(malformed)
        current = configs.read(name)
        payload = {'name':name,'revision':current['revision'],'base_content':base['content'],
                   'content':'{"Enabled":true,"added":false}', 'disk_content':'{"Enabled":true,"added":true}'}
        result = configs.merge(payload)
        self.assertEqual(result['choices'][0]['label'], 'Setting /added')
        self.assertEqual(result['current']['content'], malformed)
        self.assertEqual(result['current']['revision'], current['revision'])
        self.assertEqual(self.file.read_text(), malformed)
        self.assertFalse(configs.history_path(name).exists())
        result = configs.merge({**payload,'choices':{'0':'mine'},'resolve':True})
        self.assertEqual(configs.json.loads(result['content'])['added'], False)
        saved = configs.save({**current,'content':result['content']})
        self.assertEqual(configs.json.loads(saved['content'])['added'], False)
        self.assertEqual(configs.previous(name)['content'], malformed)

    def test_disk_corrections_must_be_valid_and_current(self):
        name = 'ModConfigs/' + self.file.name
        current = configs.read(name)
        payload = {'name':name,'revision':current['revision'],'base_content':current['content'],
                   'content':'{"Enabled":false}', 'disk_content':'{"Enabled":true "bad":1}'}
        with self.assertRaisesRegex(ValueError, 'Disk corrections are invalid'):
            configs.merge(payload)
        self.file.write_text('{"external":true}')
        with self.assertRaises(configs.ConflictError):
            configs.merge({**payload,'disk_content':'{"Enabled":true,"fixed":1}'})
        self.assertEqual(self.file.read_text(), '{"external":true}')
        self.assertFalse(configs.history_path(name).exists())

    def test_preview_gates_comparison_on_disk_syntax_and_accepts_valid_repair(self):
        name = 'ModConfigs/' + self.file.name
        base = configs.read(name)
        malformed = '{"Enabled":true "added":true}'
        self.file.write_text(malformed)
        current = configs.read(name)
        payload = {'name':name,'revision':base['revision'],'content':'{"Enabled":true,"added":false}'}
        result = configs.preview(payload)
        self.assertIn('Invalid JSON', result['disk_error'])
        self.assertIsNone(result['diff'])
        self.assertEqual(self.file.read_text(), malformed)
        corrected = '{"Enabled":true,"added":true}'
        repair = {'disk_content':corrected,'disk_revision':current['revision']}
        reviewed = configs.preview({**payload,**repair})
        self.assertIsNone(reviewed['disk_error'])
        self.assertTrue(reviewed['conflict'])
        self.assertEqual(reviewed['current']['content'],malformed)
        self.assertIn('"added":true',reviewed['diff'])
        acknowledged = configs.preview({**payload,**repair,'revision':current['revision']})
        self.assertFalse(acknowledged['conflict'])
        self.assertIsNone(acknowledged['disk_error'])
        with self.assertRaisesRegex(ValueError,'Invalid JSON'):
            configs.preview({**payload,**repair,'disk_content':'{still broken'})
        self.file.write_text('{"another":true}')
        with self.assertRaises(configs.ConflictError):
            configs.preview({**payload,**repair})
        self.assertFalse(configs.history_path(name).exists())

    def test_adjacent_matching_text_edits_are_skipped_without_a_choice(self):
        result = configs.combine_edits('a=1\nb=1\nc=1\n', 'a=2\nb=2\nc=1\n', 'a=2\nb=1\nc=3\n')
        self.assertEqual(result['content'], 'a=2\nb=2\nc=3\n')
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['choices'], [])

    def test_merge_requires_complete_valid_choices_when_resolving(self):
        name = 'ModConfigs/' + self.file.name
        self.file.write_text('{"a":1}')
        current = configs.read(name)
        payload = {'name':name,'revision':current['revision'],'base_content':'{"a":0}','content':'{"a":2}','resolve':True}
        with self.assertRaisesRegex(ValueError, 'every remaining'):
            configs.merge(payload)
        with self.assertRaisesRegex(ValueError, 'Choose your edit'):
            configs.merge({**payload, 'choices':{'0':'both'}})
        result = configs.merge({**payload, 'choices':{'0':'mine'}})
        self.assertEqual(configs.json.loads(result['content']), {'a':2})
        self.assertEqual(self.file.read_text(), '{"a":1}')
        with self.assertRaisesRegex(ValueError, 'choices changed'):
            configs.merge({**payload, 'choices':{'0':'mine','1':'disk'}})

    def test_merge_large_files_offers_manual_combination_without_losing_draft(self):
        draft = 'mine\n' + 'x' * (128 * 1024)
        result = configs.combine_edits('base', draft, 'disk')
        self.assertTrue(result['manual'])
        self.assertEqual(result['content'], draft)

    def test_merge_reads_current_disk_and_never_writes(self):
        self.file = configs.directory() / 'ModConfigs/Example.cfg'
        name = 'ModConfigs/' + self.file.name
        self.file.write_text('a\nb\nc\n')
        base = configs.read(name)
        self.file.write_text('a\nb\nC\n')
        current = configs.read(name)
        payload = {'name': name, 'revision': current['revision'], 'base_content': base['content'], 'content': 'A\nb\nc\n'}
        result = configs.merge(payload)
        self.assertEqual(result['content'], 'A\nb\nC\n')
        self.assertEqual(self.file.read_text(), 'a\nb\nC\n')
        self.assertFalse(configs.history_path(name).exists())
        with self.assertRaises(configs.ConflictError):
            configs.merge({**payload, 'revision': base['revision']})
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            configs.merge({**payload, 'base_content': None})

    def test_configs_outside_modconfigs_round_trip_and_stale_revision(self):
        for name in ('HEROsModDatabase.json', 'SomeMod/config.json', 'SomeMod/nested/options.cfg'):
            with self.subTest(name=name):
                path = configs.directory() / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"enabled": true}')
                self.assertIn(name, configs.inventory()['files'])
                current = configs.read(name)
                saved = configs.save({**current, 'content': '{"enabled": false}'})
                self.assertEqual(saved['name'], name)
                self.assertEqual(path.read_text(), '{"enabled": false}')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    configs.save(current)

    def test_non_mod_files_excluded_from_inventory_and_direct_access(self):
        names = ('Worlds/custom.json', 'Players/custom.json', 'Logs/custom.txt',
                 'Mods/enabled.json', 'ModSources/Example/config.json',
                 'config.json', 'input profiles.json', 'favorites.json', 'banlist.txt',
                 'serverconfig.txt', '.private/config.json', 'SomeMod/.secret.json',
                 'SomeMod/cache.dat', 'Worlds/World.wld')
        for name in names:
            path = configs.directory() / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        self.assertEqual(configs.inventory()['files'], ['ModConfigs/Example_Server.json'])
        for name in names:
            with self.subTest(name=name), self.assertRaises(ValueError):
                configs.read(name)

    def test_external_config_found_without_modconfigs_directory(self):
        self.file.unlink()
        self.file.parent.rmdir()
        (configs.directory() / 'HEROsModDatabase.json').write_text('{}')
        self.assertEqual(configs.inventory()['files'], ['HEROsModDatabase.json'])

    def test_nested_inventory_read_save_and_traversal(self):
        for name in ('ModConfigs/SSCS/config.json', 'ModConfigs/SSCS/Backup/config.json', 'ModConfigs/Other/config.json'):
            path = configs.directory() / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
            self.assertIn(name, configs.inventory()['files'])
            current = configs.read(name)
            configs.save({**current, 'content': '{"enabled": true}'})
            self.assertEqual(path.read_text(), '{"enabled": true}')
        for name in ('/SSCS/config.json', 'SSCS/../Example_Server.json', 'SSCS//config.json', 'SSCS/./config.json', 'SSCS\\config.json'):
            with self.assertRaises(ValueError):
                configs.read(name)

    def test_linked_child_directory_rejected(self):
        outside = settings.DATA / 'outside'
        outside.mkdir()
        (outside / 'config.json').write_text('{}')
        link = configs.directory() / 'ModConfigs/linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symbolic links unavailable on this host')
        self.assertNotIn('ModConfigs/linked/config.json', configs.inventory()['files'])
        with self.assertRaises(ValueError):
            configs.read('ModConfigs/linked/config.json')

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
                path = configs.directory() / 'ModConfigs' / name
                path.write_text(valid)
                current = configs.read('ModConfigs/' + name)
                self.assertEqual(current['format'], kind)
                self.assertIn('ModConfigs/' + name, configs.inventory()['files'])
                configs.save({**current, 'content': valid})
                self.assertEqual(path.read_bytes(), valid.encode())
                if invalid:
                    with self.assertRaisesRegex(ValueError, 'Invalid ' + kind):
                        configs.save({**configs.read('ModConfigs/' + name), 'content': invalid})
                    self.assertEqual(path.read_bytes(), valid.encode())

    def test_binary_and_unsafe_serialization_rejected(self):
        (configs.directory() / 'ModConfigs/binary.dat').write_bytes(b'\x00\xff')
        with self.assertRaises(ValueError):
            configs.read('ModConfigs/binary.dat')
        for name, content in [('config.yaml', '!!python/object:os.system {}'),
                              ('config.xml', '<!DOCTYPE config><config/>')]:
            with self.assertRaises(ValueError):
                configs.validate_content(name, content)

    def test_invalid_json_and_paths_preserve_file(self):
        original = self.file.read_text()
        for content in ('{broken', '[]', '{"value": NaN}'):
            with self.assertRaises(ValueError):
                configs.save({**configs.read('ModConfigs/' + self.file.name), 'content': content})
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
