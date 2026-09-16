"""Read a bounded prefix of Terraria world saves; never load or modify tile data.

Layout reference: TEdit/Terraria-Map-Editor, World.FileV2.cs,
LoadSectionHeader and LoadHeaderFlags (Terraria 1.3/1.4 formats 194-279).
Unsupported or incomplete saves remain selectable and report unavailable details.
"""
import datetime
import io
import struct
import uuid


class HeaderReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def take(self, count):
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError('Incomplete world header; the world may still be saving.')
        return data

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def flag(self):
        value = self.number('B')
        if value not in (0, 1):
            raise ValueError('Invalid world header flag.')
        return bool(value)

    def text(self):
        length = 0
        for shift in range(0, 35, 7):
            value = self.number('B')
            length |= (value & 127) << shift
            if not value & 128:
                if length > 4096:
                    raise ValueError('World header text is too long.')
                return self.take(length).decode('utf-8')
        raise ValueError('Invalid world header text length.')


def read_metadata(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(65536)
        reader = HeaderReader(data)
        version = reader.number('i')
        if not 194 <= version <= 279:
            return {'available': False, 'detail': f'Details unavailable for world format {version}.', 'format_version': version}
        if reader.take(7) not in (b'relogic', b'xelogic') or reader.number('B') != 2:
            raise ValueError('Unrecognized world file header.')
        revision = reader.number('I')
        reader.number('Q')  # Favorite flags.
        count = reader.number('h')
        if not 2 <= count <= 32:
            raise ValueError('Invalid world section count.')
        sections = [reader.number('i') for _ in range(count)]
        tile_count = reader.number('h')
        if tile_count < 0:
            raise ValueError('Invalid world tile flags.')
        reader.take((tile_count + 7) // 8)
        if sections[0] != reader.stream.tell() or not sections[0] < sections[1] <= len(data):
            raise ValueError('Incomplete or unsupported world header.')
        reader = HeaderReader(data[sections[0]:sections[1]])
        title, seed = reader.text(), reader.text()
        reader.number('Q')  # World generator version.
        world_guid = str(uuid.UUID(bytes_le=reader.take(16)))
        world_id = reader.number('i')
        reader.take(16)  # World pixel boundaries.
        height, width = reader.number('i'), reader.number('i')
        if not (0 < width <= 100000 and 0 < height <= 100000):
            raise ValueError('Invalid world dimensions.')
        if version >= 209:
            mode = reader.number('i')
        else:
            mode = (2 if version == 208 else 1) if reader.flag() else 0
        special = []
        if version >= 209:
            for minimum, label in [(222, 'Drunk world'), (227, 'For the worthy'),
                                   (238, 'Celebrationmk10'), (239, 'The Constant'),
                                   (241, 'Not the bees'), (249, 'Remix'), (266, 'No traps'),
                                   (267, 'Get fixed boi')]:
                if version >= minimum and reader.flag():
                    special.append(label)
            if version < 267 and 'Remix' in special and 'Drunk world' in special:
                special.append('Get fixed boi')
        ticks = reader.number('Q') & ((1 << 62) - 1)
        created = None
        if ticks:
            try:
                created = (datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=ticks // 10)).isoformat()
            except OverflowError:
                pass
        reader.take(1 + 17 * 4)  # Moon, tree and background styles.
        spawn_x, spawn_y = reader.number('i'), reader.number('i')
        reader.take(24)  # Surface, cavern layer, and current time of day (not playtime).
        reader.flag()
        reader.number('i')
        reader.flag()
        reader.flag()
        dungeon_x, dungeon_y = reader.number('i'), reader.number('i')
        evil = 'Crimson' if reader.flag() else 'Corruption'
        reader.take(11)  # Early boss progression flags.
        reader.take(7 + 2 + 1 + 4)  # Rescues/events, orbs and altar count.
        hardmode = reader.flag()
        return {'available': True, 'title': title, 'seed': seed,
                'size': {(4200, 1200): 'Small', (6400, 1800): 'Medium', (8400, 2400): 'Large'}.get((width, height), 'Custom'),
                'width': width, 'height': height,
                'difficulty': {0: 'Classic', 1: 'Expert', 2: 'Master', 3: 'Journey'}.get(mode, 'Unknown'),
                'evil': evil, 'hardmode': hardmode, 'special_seeds': special,
                'created': created, 'spawn': {'x': spawn_x, 'y': spawn_y},
                'dungeon': {'x': dungeon_x, 'y': dungeon_y},
                'world_id': world_id, 'world_guid': world_guid,
                'format_version': version, 'save_revision': revision}
    except (OSError, ValueError, struct.error) as error:
        return {'available': False, 'detail': str(error)}
