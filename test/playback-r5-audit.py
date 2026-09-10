"""Non-live audit of exact published r5 methods, including native Windows fixtures.

Usage: python test_playback_windows_r5_audit.py [path/to/r5.zip]
No driver module, graph, credentials, network or audio is loaded. All writes go to
an explicit TemporaryDirectory. Windows sharing tests skip on other platforms.
The final-OFF test documents an existing limitation; it is not proof of a fix.
"""
import ast
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import zipfile


EXPECTED_SHA256 = '43335262bbfe5ebacd6f722112ed6e584ad3bab282315621b731303d0f825281'
ZIP = (Path(sys.argv.pop(1)) if len(sys.argv) > 1 and not sys.argv[1].startswith('-')
       else Path(__file__).resolve().parents[1] / 'mini-mouth-windows-candidate-2026-09-11-r5.zip')
if hashlib.sha256(ZIP.read_bytes()).hexdigest() != EXPECTED_SHA256:
    raise SystemExit('REFUSED: archive SHA256 does not match published r5')
with zipfile.ZipFile(ZIP) as archive:
    SOURCE = archive.read('mini-mouth/src/rt_driver.py').decode('utf-8')
BODY = next(node.body for node in ast.parse(SOURCE).body
            if isinstance(node, ast.ClassDef) and node.name == 'Driver')


def extract(name, namespace, parent=None):
    candidates = BODY if parent is None else ast.walk(next(
        node for node in BODY if getattr(node, 'name', None) == parent))
    node = next(node for node in candidates if getattr(node, 'name', None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'published-r5/rt_driver.py', 'exec'), namespace)
    return namespace[name]


class PublishedFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='playback-r5-audit-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fixture space \u05e9\u05dc\u05d5\u05dd' / 'playback.json'
        self.driver = types.SimpleNamespace(PLAYBACK=str(self.path), _mic_level_or_zero=lambda: 5)
        namespace = dict(os=os, json=json, time=time, now_ms=lambda: 123456)
        self.publish = types.MethodType(extract('publish_playback', namespace), self.driver)
        self.driver.publish_playback = self.publish

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def cursor(self, on_sleep):
        player = types.SimpleNamespace(active=True, fed_ms=1, level=77,
                                       pos_ms=1, ms=1, starve_ms=0)
        self.driver.player = player
        self.driver.put = lambda *args: None
        self.driver.rt = types.SimpleNamespace(status=object())

        async def sleep(seconds):
            self.assertEqual(seconds, .15)
            on_sleep()
            player.active = False

        namespace = dict(self=self.driver, player=player, rt=self.driver.rt, time=time,
                         asyncio=types.SimpleNamespace(sleep=sleep))
        return extract('cursor_pump', namespace, parent='handle_server')

    def test_actual_unicode_path_and_closed_writer_handle_allow_replace(self):
        self.publish(False, 'mouth')
        self.publish(True, 'mouth', 77)
        self.publish(False, 'mouth')
        self.assertEqual(self.read(), dict(v=1, on_air=False, src='mouth', level=0,
                                         mic_level=5, call=f'mini-mouth-{os.getpid()}', ts=123456))

    def test_final_off_failure_has_no_automatic_idle_retry(self):
        real_replace = os.replace
        output = io.StringIO()
        attempts = []

        def replace(source, target):
            attempts.append(json.loads(Path(source).read_text(encoding='utf-8'))['on_air'])
            if len(attempts) == 2:
                raise PermissionError(13, 'synthetic sharing refusal')
            real_replace(source, target)

        pump = self.cursor(lambda: None)
        with patch.object(os, 'replace', side_effect=replace), contextlib.redirect_stdout(output):
            asyncio.run(pump())
        self.assertEqual(attempts, [True, False])
        self.assertTrue(self.read()['on_air'])
        self.assertEqual(self.driver._pb_last, (True, 'mouth'))
        self.assertEqual(output.getvalue().count('metadata write failed'), 1)
        # The completed cursor schedules no retry. A later explicit publication
        # does recover, so caching did not mistake the failed OFF for success.
        self.publish(False, 'mouth')
        self.assertFalse(self.read()['on_air'])

    def test_unwritable_parent_is_reported_without_private_error_text(self):
        self.path.parent.parent.mkdir(exist_ok=True)
        self.path.parent.write_text('fixture path collision', encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.publish(False, 'mouth')
        self.assertIn('metadata write failed', output.getvalue())
        self.assertNotIn(str(self.path), output.getvalue())
        self.assertFalse(hasattr(self.driver, '_pb_last'))
        self.path.parent.unlink()
        self.publish(False, 'mouth')
        self.assertFalse(self.read()['on_air'])

    @contextlib.contextmanager
    def windows_reader_without_delete_share(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        # GENERIC_READ; FILE_SHARE_READ | FILE_SHARE_WRITE, deliberately excluding
        # FILE_SHARE_DELETE; OPEN_EXISTING; FILE_ATTRIBUTE_NORMAL. Fixture only.
        handle = create(str(self.path), 0x80000000, 3, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not close(handle):
                raise ctypes.WinError(ctypes.get_last_error())

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing semantics')
    def test_native_windows_reader_blocks_replace_then_next_active_tick_recovers(self):
        self.publish(False, 'mouth')
        output = io.StringIO()
        with self.windows_reader_without_delete_share(), contextlib.redirect_stdout(output):
            self.publish(True, 'mouth', 77)
            self.assertFalse(self.read()['on_air'])
        errors = re.findall(r'winerror=(\d+)', output.getvalue())
        self.assertTrue(errors, output.getvalue())
        self.assertTrue(all(int(code) in (5, 32, 33) for code in errors), errors)
        self.publish(True, 'mouth', 77)
        self.assertTrue(self.read()['on_air'])

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing semantics')
    def test_native_windows_reader_can_leave_final_off_stale_until_next_call(self):
        held = contextlib.ExitStack()
        self.addCleanup(held.close)
        pump = self.cursor(lambda: held.enter_context(self.windows_reader_without_delete_share()))
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                asyncio.run(pump())
        finally:
            held.close()
        errors = re.findall(r'winerror=(\d+)', output.getvalue())
        self.assertTrue(errors, output.getvalue())
        self.assertTrue(all(int(code) in (5, 32, 33) for code in errors), errors)
        self.assertTrue(self.read()['on_air'])
        self.publish(False, 'mouth')
        self.assertFalse(self.read()['on_air'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
