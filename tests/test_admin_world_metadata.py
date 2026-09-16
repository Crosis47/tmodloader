import datetime
import struct
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin_world_metadata import read_metadata


def world_header(version=279, mode=2, crimson=True, hardmode=True):
    # Terraria section/header fixture; no tile data is needed for metadata.
    def text(value):
        data = value.encode('utf-8')
        length, prefix = len(data), bytearray()
        while length >= 128:
            prefix.append((length & 127) | 128)
            length >>= 7
        return bytes(prefix) + bytes([length]) + data

    header = text('Test 世界') + text('seed-' + 'x' * 150)
    header += struct.pack('<Q16si4i2i', 123, bytes(range(16)), 42, 0, 67200, 0, 19200, 1200, 4200)
    header += struct.pack('<i', mode) if version >= 209 else bytes([mode != 0])
    for minimum in (222, 227, 238, 239, 241, 249, 266, 267):
        if version >= minimum:
            header += bytes([minimum == 227])
    ticks = (datetime.datetime(2026, 1, 2) - datetime.datetime(1, 1, 1)).days * 864000000000
    header += struct.pack('<Q', ticks)
    header += bytes(1 + 17 * 4)
    header += struct.pack('<ii3dBiBBiiB', 2100, 300, 350.0, 600.0, 12345.0, 1, 3, 0, 0, 400, 350, crimson)
    header += bytes(11 + 7 + 2 + 1 + 4) + bytes([hardmode])
    start = 4 + 7 + 1 + 4 + 8 + 2 + 8 + 2 + 1
    return struct.pack('<i7sBIQhii', version, b'relogic', 2, 7, 0, 2, start, start + len(header)) + struct.pack('<hB', 8, 0) + header


class MetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'Test.wld'

    def read(self, data):
        self.path.write_bytes(data)
        result = read_metadata(self.path)
        self.assertEqual(self.path.read_bytes(), data)
        return result

    def test_saved_values_and_unicode(self):
        result = self.read(world_header())
        self.assertTrue(result['available'], result)
        for key, expected in {'title': 'Test 世界', 'size': 'Small', 'width': 4200,
                              'height': 1200, 'difficulty': 'Master', 'evil': 'Crimson',
                              'hardmode': True, 'created': '2026-01-02T00:00:00',
                              'world_id': 42, 'save_revision': 7, 'format_version': 279,
                              'special_seeds': ['For the worthy'],
                              'spawn': {'x': 2100, 'y': 300},
                              'dungeon': {'x': 400, 'y': 350}}.items():
            self.assertEqual(result[key], expected, key)
        self.assertEqual(result['seed'], 'seed-' + 'x' * 150)
        self.assertNotIn('playtime', result)

    def test_version_layout_boundaries(self):
        for version in (194, 208, 209, 222, 227, 238, 239, 241, 249, 266, 267, 279):
            with self.subTest(version=version):
                result = self.read(world_header(version, mode=0, crimson=False, hardmode=False))
                self.assertTrue(result['available'], result)
                self.assertEqual(result['difficulty'], 'Classic')
                self.assertEqual(result['evil'], 'Corruption')
                self.assertFalse(result['hardmode'])

    def test_modes(self):
        for mode, label in enumerate(['Classic', 'Expert', 'Master', 'Journey']):
            self.assertEqual(self.read(world_header(mode=mode))['difficulty'], label)

    def test_truncated_header(self):
        data = world_header()
        for length in (0, 3, 20, 40, len(data) - 1):
            self.assertFalse(self.read(data[:length])['available'])

    def test_unsupported_and_invalid_headers(self):
        for version in (0, 193, 280, 9999):
            self.assertFalse(self.read(struct.pack('<i', version))['available'])
        data = bytearray(world_header())
        data[4:11] = b'notawld'
        self.assertFalse(self.read(data)['available'])
        data = bytearray(world_header())
        struct.pack_into('<i', data, 30, 99999999)
        self.assertFalse(self.read(data)['available'])
        self.path.unlink()
        self.assertFalse(read_metadata(self.path)['available'])
