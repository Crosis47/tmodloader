"""Download one Workshop item natively, preserving the last complete cache."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


def download(content_root, item_id, manifest, updated, executable='depotdownloader'):
    if not re.fullmatch(r'[0-9]+', item_id):
        raise ValueError('Invalid Workshop item ID')
    root = Path(content_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / item_id
    if target.is_symlink():
        raise ValueError('Workshop item directory must not be a symlink')
    # Use the exact manifest obtained from Steam where available, so the cache
    # is never marked current using metadata from a different download.
    exact_manifest = bool(re.fullmatch(r'[0-9]+', manifest) and int(manifest))
    selector = ['-ugc', manifest] if exact_manifest else ['-pubfile', item_id]
    with tempfile.TemporaryDirectory(prefix='.download-', dir=root) as temporary:
        temporary = Path(temporary)
        staging = temporary / 'content'
        command = [executable, '-app', '1281930', *selector, '-dir', str(staging), '-validate']
        result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, end='', flush=True)
        result.check_returncode()
        if not re.search(r'^Total downloaded: .+ from 1 depots\s*$', result.stdout, re.MULTILINE):
            raise RuntimeError(f'Workshop item {item_id} did not finish downloading')
        # DepotDownloader can exit zero after failing to resolve an item.
        # A fresh staging directory prevents stale files from hiding that error.
        mods = list(staging.rglob('*.tmod'))
        if not mods:
            raise RuntimeError(f'Workshop item {item_id} produced no .tmod files')
        for mod in mods:
            with mod.open('rb') as stream:
                if stream.read(4) != b'TMOD':
                    raise RuntimeError(f'Workshop item {item_id} produced an invalid .tmod file')
        (staging / '.tmodloader-download.json').write_text(json.dumps({
            'manifest': manifest if exact_manifest else '',
            'timeupdated': updated if exact_manifest else '',
        }), encoding='utf-8')
        # Keep recovery data outside the temporary directory so even a failed
        # rollback cannot make TemporaryDirectory erase the last good cache.
        previous = root / f'.previous-{item_id}-{uuid.uuid4().hex}'
        if target.exists():
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except BaseException:
            if previous.exists():
                try:
                    os.replace(previous, target)
                except OSError as error:
                    raise RuntimeError(f'Cached mod preserved for recovery at {previous}') from error
            raise
        if previous.exists():
            shutil.rmtree(previous)


if __name__ == '__main__':
    try:
        download(*sys.argv[1:])
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'[!!] Native Workshop download failed: {error}', file=sys.stderr)
        sys.exit(1)
