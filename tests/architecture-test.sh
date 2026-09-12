#!/usr/bin/env bash
set -Eeuo pipefail

# Inspect the actual executable headers: uname alone can hide accidental
# x86 emulation inside an image advertised as ARM64.
python3 - <<'PY'
import platform
import struct
from pathlib import Path

machine = platform.machine()
expected = {'x86_64': 62, 'aarch64': 183, 'arm64': 183}[machine]
for filename in ('/usr/bin/python3', '/usr/bin/tini', '/terraria-server/dotnet/dotnet'):
    header = Path(filename).read_bytes()[:20]
    assert header[:4] == b'\x7fELF', filename
    actual = struct.unpack('<H', header[18:20])[0]
    assert actual == expected, (filename, machine, actual)
if expected == 183:
    header = Path('/opt/depotdownloader/DepotDownloader').read_bytes()[:20]
    assert struct.unpack('<H', header[18:20])[0] == 183, 'Workshop downloader must be native ARM64'
    assert not Path('/usr/bin/steamcmd').exists(), 'ARM64 must not depend on x86 SteamCMD'
else:
    steam = Path('/opt/steamcmd-seed/linux32/steamcmd').read_bytes()[:20]
    assert struct.unpack('<H', steam[18:20])[0] == 3, 'SteamCMD must remain isolated x86'
print(f'Native {machine} runtime and platform Workshop downloader verified.')
PY
/terraria-server/dotnet/dotnet --info
