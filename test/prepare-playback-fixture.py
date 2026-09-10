"""Prepare one public, hash-verified source file for isolated metadata tests."""
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
    for filename in ('rt_driver.py', 'tap_log.py'):
        source = archive.read('mini-mouth/src/' + filename)
        target = Path('fixture/mini-mouth/src') / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
print('Verified public r5 archive; extracted two source files for non-live tests.')
