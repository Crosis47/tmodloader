"""Remove explicitly client-only Workshop mods from the enabled server list."""
import json
import os
from pathlib import Path
import sys
import tempfile


def filter_enabled(data):
    enabled = data / 'tModLoader/Mods/enabled.json'
    if not enabled.exists():
        return []
    values = json.loads(enabled.read_text())
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError('enabled.json must be an array of mod names')
    classifications = {}
    root = data / 'steamMods/steamapps/workshop/content/1281930'
    for metadata in root.glob('*/workshop.json'):
        try:
            tags = {tag.casefold() for tag in json.loads(metadata.read_text()).get('Tags', []) if isinstance(tag, str)}
        except (OSError, ValueError, AttributeError, TypeError):
            continue
        client = 'client' in tags and not tags.intersection({'both', 'server'})
        for mod in metadata.parent.rglob('*.tmod'):
            classifications.setdefault(mod.stem, []).append(client)
    removed = [name for name in values if classifications.get(name) and all(classifications[name])]
    if removed:
        fd, temporary = tempfile.mkstemp(dir=enabled.parent, prefix='enabled-filter-', suffix='.json')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump([name for name in values if name not in removed], stream, indent=2)
                stream.write('\n')
            os.replace(temporary, enabled)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        for name in removed:
            print(f'[SYSTEM] Removed client-only mod {name} from enabled.json; cached files retained.')
        from admin_settings import record_removed
        record_removed(removed)
    return removed


if __name__ == '__main__':
    filter_enabled(Path(sys.argv[1]))
