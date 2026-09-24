from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import character_bridge as bridge
import admin_settings as settings
import runtime_updates


class CharacterBridgeTests(unittest.TestCase):
    def test_cached_build_rebuilds_after_restore_or_runtime_change_without_losing_mod_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            runtime.mkdir()
            (runtime / 'tModLoader.dll').write_bytes(b'first runtime')
            data = root / 'data'
            mods = data / 'tModLoader/Mods'
            settings.atomic_json(mods / 'enabled.json', ['UserMod'])
            builds = []
            def build(command, **kwargs):
                builds.append(command)
                target = Path(command[command.index('-tmlsavedirectory') + 1]) / 'Mods/ContainerCharacters.tmod'
                target.parent.mkdir(parents=True)
                target.write_bytes(b'current build')
            with patch.object(runtime_updates, 'dotnet', return_value=runtime / 'dotnet'), \
                    patch.object(bridge.subprocess, 'run', side_effect=build):
                bridge.prepare(runtime, data)
                bridge.prepare(runtime, data)
                self.assertEqual(len(builds), 1)
                self.assertEqual(settings.read_json(mods / 'enabled.json'), ['UserMod', 'ContainerCharacters'])
                (mods / 'ContainerCharacters.tmod').write_bytes(b'restored older build')
                bridge.prepare(runtime, data)
                self.assertEqual(len(builds), 2)
                (runtime / 'tModLoader.dll').write_bytes(b'next runtime')
                bridge.prepare(runtime, data)
                self.assertEqual(len(builds), 3)

    def test_failed_build_leaves_previous_mod_and_selection_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tModLoader.dll').write_bytes(b'runtime')
            mods = root / 'data/tModLoader/Mods'
            settings.atomic_json(mods / 'enabled.json', ['UserMod'])
            (mods / 'ContainerCharacters.tmod').write_bytes(b'old build')
            with patch.object(runtime_updates, 'dotnet', return_value=root / 'dotnet'), \
                    patch.object(bridge.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'build')):
                with self.assertRaises(subprocess.CalledProcessError):
                    bridge.prepare(root, root / 'data')
            self.assertEqual((mods / 'ContainerCharacters.tmod').read_bytes(), b'old build')
            self.assertEqual(settings.read_json(mods / 'enabled.json'), ['UserMod'])
