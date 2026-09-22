import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import zipfile

import admin_settings as settings
import admin_updates as updates
import runtime_updates as updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'data'
        self.base = self.root / 'image'
        self.base.mkdir()
        self.control = self.data / '.tmod-control/updates'
        self.control.mkdir(parents=True)
        for target, key, value in ((updates, 'ROOT', self.control), (updates, 'BASE', self.base),
                                   (settings, 'DATA', self.data)):
            mocked = patch.object(target, key, value)
            mocked.start(); self.addCleanup(mocked.stop)
        env = patch.dict(os.environ, {'TMOD_AUTO_UPDATE': '1', 'TMOD_UPDATE_CHANNEL': 'stable',
                                     'TMOD_UPDATE_VERSION': '', 'TMOD_UPDATE_MIN_FREE_MB': '0',
                                     'TMOD_USECONFIGFILE': 'No'})
        env.start(); self.addCleanup(env.stop)
        self.old = {'tmodloader_version': 'v2026.06.3.0', 'tmodloader_sha256': 'old', 'container_version': 'test'}
        settings.atomic_json(self.base / 'backup-runtime.json', self.old)
        for name, content in {'steamMods/example.tmod': 'old-mod', 'tModLoader/Mods/enabled.json': '["Example"]',
                              'tModLoader/Worlds/World.wld': 'original-world',
                              'tModLoader/ModConfigs/Example.json': '{}',
                              'admin/settings.json': '{"TMOD_WORLDNAME":"World"}'}.items():
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.config = self.base / 'serverconfig.txt'
        self.config.write_text('world=' + str(self.data / 'tModLoader/Worlds/World.wld'))
        self.candidate = self.control / 'releases/v2026.07.3.0'
        self.candidate.mkdir(parents=True)
        (self.candidate / 'tModLoader.dll').write_text('candidate')
        self.new = {'tmodloader_version': 'v2026.07.3.0', 'tmodloader_sha256': 'new'}

    def prepare(self, probe=None):
        def download_mods(*args, **kwargs):
            staged = Path(kwargs['env']['TMOD_DATA_DIR'])
            (staged / 'steamMods/example.tmod').write_text('new-mod')
        with patch.object(updater, 'cache_bundled'), patch.object(updates, 'check', return_value={
                'latest': {'version': self.new['tmodloader_version']}}), \
                patch.object(updater, 'download', return_value=(self.candidate, self.new)), \
                patch.object(updater.subprocess, 'run', side_effect=download_mods), \
                patch.object(updater, 'probe', side_effect=probe):
            updater.prepare(self.config)

    def test_failed_probe_preserves_runtime_world_and_mods(self):
        self.prepare(ValueError('Missing dependency ExampleLibrary'))
        self.assertEqual(updates.active(), self.base)
        self.assertEqual((self.data / 'steamMods/example.tmod').read_text(), 'old-mod')
        self.assertEqual((self.data / 'tModLoader/Worlds/World.wld').read_text(), 'original-world')
        self.assertEqual(updates.read(self.control / 'status.json')['state'], 'blocked')
        self.assertFalse((self.control / 'checkpoint.json').exists())

    def test_success_keeps_live_world_and_rollback_restores_paired_data(self):
        def mutate_trial(runtime, data, config, log):
            (data / 'tModLoader/Worlds/World.wld').write_text('trial-changes')
        self.prepare(mutate_trial)
        self.assertEqual(updates.active(), self.candidate)
        self.assertTrue((self.control / 'journal.json').exists())
        # The supervisor commits only after live readiness succeeds.
        (self.control / 'journal.json').unlink()
        self.assertEqual((self.data / 'steamMods/example.tmod').read_text(), 'new-mod')
        self.assertEqual((self.data / 'tModLoader/Worlds/World.wld').read_text(), 'original-world')
        (self.data / 'tModLoader/Worlds/World.wld').write_text('later-progress')
        settings.atomic_json(self.control / 'rollback-request.json', {})
        updater.boot()
        self.assertEqual(updates.active(), self.base)
        self.assertEqual((self.data / 'steamMods/example.tmod').read_text(), 'old-mod')
        self.assertEqual((self.data / 'tModLoader/Worlds/World.wld').read_text(), 'original-world')
        self.assertEqual(updates.read(self.control / 'hold.json')['version'], self.old['tmodloader_version'])
        retained = updater.transaction(updates.read(self.control / 'checkpoint.json')['id'])
        self.assertEqual((retained / 'before/tModLoader/Worlds/World.wld').read_text(), 'later-progress')

    def test_interrupted_promotion_replays_checkpoint(self):
        identity, _ = updater.snapshot()
        settings.atomic_json(self.control / 'journal.json', {'checkpoint': identity})
        (self.data / 'steamMods/example.tmod').write_text('partial')
        settings.atomic_json(self.control / 'active.json', self.new)
        updater.boot()
        self.assertEqual(updates.active(), self.base)
        self.assertEqual((self.data / 'steamMods/example.tmod').read_text(), 'old-mod')
        self.assertFalse((self.control / 'journal.json').exists())

    def test_network_failure_never_refreshes_live_mods(self):
        with patch.object(updater, 'cache_bundled'), patch.object(updates, 'check', return_value={'error': 'Offline'}), \
                patch.object(updater.subprocess, 'run') as run:
            updater.prepare(self.config)
        run.assert_not_called()
        self.assertEqual((self.data / 'steamMods/example.tmod').read_text(), 'old-mod')

    def test_recovery_pin_blocks_automatic_upgrade(self):
        settings.atomic_json(self.control / 'hold.json', {'version': self.old['tmodloader_version']})
        with patch.object(updater, 'cache_bundled'), patch.object(updates, 'check', return_value={
                'latest': {'version': self.new['tmodloader_version']}}), \
                patch.object(updater, 'download') as download, \
                patch.object(updater.subprocess, 'run'), patch.object(updater, 'probe') as probe:
            updater.prepare(self.config)
        download.assert_not_called()
        probe.assert_not_called()

    def test_release_filter_excludes_legacy_preview_and_missing_assets(self):
        tag = 'v2026.07.3.0'
        item = {'tag_name': tag, 'name': '1.4.4-refs/heads/stable Version Update: ' + tag,
                'assets': [{'name': 'tModLoader.zip', 'browser_download_url':
                            f'https://github.com/tModLoader/tModLoader/releases/download/{tag}/tModLoader.zip'}]}
        self.assertIsNotNone(updates.release(item, 'stable'))
        for changed in ({'prerelease': True}, {'draft': True}, {'name': '1.4.3-Legacy'}, {'assets': []}):
            self.assertIsNone(updates.release({**item, **changed}, 'stable'))
        self.assertGreater(updates.version('v2026.10.3.0'), updates.version('v2026.9.3.0'))

    def test_zip_traversal_and_symlinks_rejected(self):
        for name in ('../escape', '/absolute', 'C:/outside', 'bad\\path'):
            archive = self.root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr(name, 'bad')
            with self.assertRaises(ValueError):
                updater.extract(archive, self.root / 'extracted')
        if os.name == 'posix':
            (self.data / 'steamMods/link').symlink_to(self.base)
            with self.assertRaises(ValueError):
                updater.snapshot()

    def test_stale_release_remains_visible_but_error_is_explicit(self):
        settings.atomic_json(self.control / 'check.json', {'channel': 'stable', 'latest': {'version': 'v2026.07.3.0'},
                                                         'checked_at': 'old'})
        with patch.object(updates.urllib.request, 'urlopen', side_effect=OSError('network unavailable')):
            result = updates.check()
        self.assertIn('network unavailable', result['error'])
        self.assertEqual(result['checked_at'], 'old')
        self.assertTrue(updates.status(refresh=False)['available'])

    def test_rollback_api_needs_auth_confirmation_and_idle_state(self):
        import admin_server as server
        with patch.object(server, 'operation_busy', return_value=False):
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                server.api('POST', '/api/updates/rollback', {}, {})
        with patch.object(server, 'operation_busy', return_value=True):
            with self.assertRaisesRegex(ValueError, 'current operation'):
                server.api('POST', '/api/updates/cancel', {}, {'confirm': True})
        with patch.object(server.admin_access, 'check_request'):
            responses = []
            server.application({'PATH_INFO': '/api/updates/rollback', 'REQUEST_METHOD': 'POST'},
                               lambda status, headers: responses.append(status))
        self.assertEqual(responses, ['403 Forbidden'])

    def test_native_probe_requires_every_enabled_mod_even_if_server_starts(self):
        logs = self.data / 'tModLoader/Logs'
        logs.mkdir(parents=True)
        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = 0
        child.stdin = io.StringIO()
        for loaded in ('', 'Finalizing Content: Example (Example mod) v1.0\n'):
            (logs / 'server.log').write_text(loaded + 'Mod Load Completed\nServer started\n')
            with patch.object(updater, 'dotnet', return_value=self.base / 'dotnet'), \
                    patch.object(updater.subprocess, 'Popen', return_value=child), patch.object(updater.os, 'killpg'):
                if loaded:
                    updater.probe_process(self.base, self.data, self.config, self.root / 'probe.log')
                else:
                    with self.assertRaisesRegex(ValueError, 'did not load enabled mods: Example'):
                        updater.probe_process(self.base, self.data, self.config, self.root / 'probe.log')

    def test_linked_world_parent_is_rejected(self):
        if os.name != 'posix':
            self.skipTest('POSIX symlink test')
        source = self.data / 'tModLoader'
        source.rename(self.root / 'outside')
        source.symlink_to(self.root / 'outside', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Linked game-data'):
            updater.snapshot()

    def test_probe_restores_log_routing_after_failure(self):
        with patch.object(updater, 'probe_process', side_effect=ValueError('bad mod')):
            with self.assertRaises(ValueError):
                updater.probe(self.candidate, self.root / 'trial', self.config, self.root / 'probe.log')
        self.assertEqual((self.candidate / 'tModLoader-Logs').resolve(), self.data / 'tModLoader/Logs')

    def test_custom_config_blocks_update_without_touching_mods(self):
        with patch.dict(os.environ, {'TMOD_USECONFIGFILE': 'Yes'}), patch.object(updates, 'check') as check, \
                patch.object(updater.subprocess, 'run') as run:
            updater.prepare(self.config)
        check.assert_not_called()
        run.assert_not_called()
        self.assertEqual(updates.read(self.control / 'status.json')['state'], 'blocked')

    def test_no_first_world_is_created_after_failed_mod_preparation(self):
        (self.data / 'tModLoader/Worlds/World.wld').unlink()
        with patch.dict(os.environ, {'TMOD_MODS': '123'}):
            with self.assertRaisesRegex(RuntimeError, 'without the requested mods'):
                self.prepare(ValueError('Missing dependency'))

    def test_early_startup_failure_unblocks_dashboard_recovery(self):
        import admin_server as server
        updater.report('initializing', 'Starting')
        with patch.dict(os.environ, {'TMOD_AUTO_UPDATE': '0'}), \
                patch.object(sys, 'argv', ['runtime_updates.py', 'prepare', str(self.config)]), \
                patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'manage-mods.sh')):
            with self.assertRaises(subprocess.CalledProcessError):
                runpy.run_path(str(Path(updater.__file__)), run_name='__main__')
        self.assertEqual(updates.read(self.control / 'status.json')['state'], 'blocked')
        with patch.object(server, 'operation_busy', return_value=False):
            result = server.api('POST', '/api/updates/cancel', {}, {'confirm': True})
        self.assertFalse(result['rollback_pending'])

    def test_bundled_library_alias_is_materialized_but_external_links_are_rejected(self):
        library = self.base / 'Libraries'
        library.mkdir()
        (library / 'actual.so').write_bytes(b'library')
        (library / 'alias.so').symlink_to(library / 'actual.so')
        target = self.root / 'cached-libraries'
        updater.copy_bundled(library, target)
        self.assertEqual((target / 'alias.so').read_bytes(), b'library')
        self.assertFalse((target / 'alias.so').is_symlink())
        (library / 'external.so').symlink_to(self.config.parent.parent / 'outside.so')
        (self.root / 'outside.so').write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'runtime link'):
            updater.copy_bundled(library, self.root / 'rejected')

    def test_checkpoint_delete_preserves_live_data_and_rejects_pending_recovery(self):
        identity, directory = updater.snapshot()
        settings.atomic_json(self.control / 'checkpoint.json', {'id': identity})
        with self.assertRaisesRegex(ValueError, 'changed'):
            updater.delete_checkpoint('0' * 32)
        settings.atomic_json(self.control / 'rollback-request.json', {})
        with self.assertRaisesRegex(ValueError, 'pending recovery'):
            updater.delete_checkpoint(identity)
        (self.control / 'rollback-request.json').unlink()
        updater.delete_checkpoint(identity)
        self.assertFalse(directory.exists())
        self.assertFalse((self.control / 'checkpoint.json').exists())
        self.assertEqual((self.data / 'tModLoader/Worlds/World.wld').read_text(), 'original-world')

    def test_checkpoint_delete_api_requires_confirmation_and_health(self):
        import admin_server as server
        with patch.object(server, 'operation_busy', return_value=False):
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                server.api('POST', '/api/updates/delete-checkpoint', {}, {})
            with patch.object(server, 'health', return_value=False):
                with self.assertRaisesRegex(ValueError, 'healthy'):
                    server.api('POST', '/api/updates/delete-checkpoint', {}, {'confirm': True})

    def test_recovery_cleanup_waits_for_health_and_removes_both_copies(self):
        first, first_path = updater.snapshot()
        second, second_path = updater.snapshot()
        settings.atomic_json(self.control / 'checkpoint.json', {'id': second})
        updater.mark_recovery_cleanup(first, second)
        with patch.object(updater.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'healthcheck')):
            with self.assertRaises(subprocess.CalledProcessError):
                updater.finish_recovery()
        self.assertTrue(first_path.exists())
        self.assertTrue(second_path.exists())
        with patch.object(updater.subprocess, 'run'):
            updater.finish_recovery()
        self.assertFalse(first_path.exists())
        self.assertFalse(second_path.exists())
        self.assertFalse((self.control / 'checkpoint.json').exists())
        self.assertFalse((self.control / 'recovery-cleanup.json').exists())
        self.assertEqual((self.data / 'tModLoader/Worlds/World.wld').read_text(), 'original-world')

    def test_announcements_are_opt_in_and_deduplicated(self):
        state = {'available': True, 'error': '', 'operation': {}, 'latest': {'version': 'v2026.07.3.0'}, 'channel': 'stable'}
        with patch.object(updates, 'status', return_value=state), patch.object(updates, 'request_check'), \
                patch.object(updates.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            updates.announce_available()
            run.assert_not_called()
            settings.atomic_json(self.control / 'announcements.json', {'enabled': True})
            updates.announce_available()
            self.assertEqual(run.call_count, 2)
            self.assertIn('v2026.07.3.0', run.call_args.args[0][1])
            updates.announce_available()
            self.assertEqual(run.call_count, 2)

    def test_failed_announcement_is_not_marked_sent(self):
        settings.atomic_json(self.control / 'announcements.json', {'enabled': True})
        state = {'available': True, 'error': '', 'operation': {}, 'latest': {'version': 'v2026.07.3.0'}, 'channel': 'stable'}
        with patch.object(updates, 'status', return_value=state), patch.object(updates, 'request_check'), \
                patch.object(updates.subprocess, 'run', side_effect=[Mock(returncode=0), Mock(returncode=1)]):
            updates.announce_available()
        self.assertFalse((self.control / 'announced.json').exists())

    def test_container_notice_uses_container_semver_and_channel_with_cache(self):
        (self.base / 'VERSION').write_text('3.9.0')
        releases = [{'tag_name': '3.10.0', 'draft': False, 'prerelease': False},
                    {'tag_name': '4.0.0-preview', 'draft': False, 'prerelease': True},
                    {'tag_name': '9.0.0', 'draft': True, 'prerelease': False}]
        with patch.object(updates.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(releases).encode())) as fetch:
            result = updates.container_status()
            self.assertTrue(result['available'])
            self.assertEqual(result['latest'], '3.10.0')
            self.assertEqual(updates.container_status()['latest'], '3.10.0')
            fetch.assert_called_once()

    def test_container_check_failure_is_cached_without_false_notice(self):
        (self.base / 'VERSION').write_text('3.4.0')
        with patch.object(updates.urllib.request, 'urlopen', side_effect=OSError('offline')) as fetch:
            self.assertFalse(updates.container_status()['available'])
            self.assertTrue(updates.container_status()['error'])
            fetch.assert_called_once()

    def test_only_explicit_restart_clears_hold(self):
        settings.atomic_json(self.control / 'hold.json', {'version': self.old['tmodloader_version']})
        updater.boot()
        self.assertTrue((self.control / 'hold.json').exists())
        updater.boot(retry=True)
        self.assertFalse((self.control / 'hold.json').exists())

    def test_cancel_recovery_preserves_hold(self):
        import admin_server as server
        settings.atomic_json(self.control / 'hold.json', {'version': self.old['tmodloader_version']})
        settings.atomic_json(self.control / 'rollback-request.json', {})
        with patch.object(server, 'operation_busy', return_value=False):
            server.api('POST', '/api/updates/cancel', {}, {'confirm': True})
        self.assertTrue((self.control / 'hold.json').exists())
        self.assertFalse((self.control / 'rollback-request.json').exists())

    def test_dashboard_restart_requires_confirmation_and_queues_supervisor(self):
        import admin_server as server
        with patch.object(server, 'operation_busy', return_value=False), \
                patch.object(server.admin_recovery, 'status', return_value={'interrupted': False}), \
                patch.object(server, 'start_job', return_value={'state': 'running'}) as start:
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                server.api('POST', '/api/updates/restart', {}, {})
            start.assert_not_called()
            self.assertEqual(server.api('POST', '/api/updates/restart', {}, {'confirm': True}), {'state': 'running'})
            start.assert_called_once_with('runtime-update')
        with patch.object(server, 'operation_busy', return_value=True):
            with self.assertRaisesRegex(ValueError, 'current operation'):
                server.api('POST', '/api/updates/restart', {}, {'confirm': True})


if __name__ == '__main__':
    unittest.main()
