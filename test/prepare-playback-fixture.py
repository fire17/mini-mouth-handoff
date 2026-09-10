"""Prepare public, hash-verified source files for isolated metadata tests."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ARCHIVE = Path('fixture-r5.zip')
SHA256 = '43335262bbfe5ebacd6f722112ed6e584ad3bab282315621b731303d0f825281'
URL = ('https://github.com/fire17/mini-mouth-handoff/releases/download/v0.1.3/'
       'mini-mouth-windows-candidate-2026-09-11-r5.zip')
with urllib.request.urlopen(URL, timeout=60) as response:
    data = response.read(2 * 1024 * 1024)
if hashlib.sha256(data).hexdigest() != SHA256:
    raise SystemExit('REFUSED: release archive SHA256 mismatch')
ARCHIVE.write_bytes(data)
with zipfile.ZipFile(ARCHIVE) as archive:
    total = 0
    count = 0
    for item in archive.infolist():
        name = Path(item.filename)
        if name.is_absolute() or '..' in name.parts or '\\' in item.filename:
            raise SystemExit('REFUSED: invalid fixture path')
        if not name.parts or name.parts[0] not in ('mini-mouth', 'XO') or item.is_dir():
            continue
        total += item.file_size
        if total > 16 * 1024 * 1024:
            raise SystemExit('REFUSED: fixture expansion exceeded limit')
        target = Path('fixture') / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(item))
        count += 1
print(f'Verified public r5 archive; extracted {count} source fixture files for non-live tests.')
