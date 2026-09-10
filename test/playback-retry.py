"""Isolated candidate races: actual extracted methods, no live imports/audio/graph."""
import argparse
import ast
import asyncio
import contextlib
import io
import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path,
                    default=ROOT / 'candidate-playback-retry/mini-mouth/src/rt_driver.py')
options, remaining_args = parser.parse_known_args()
sys.argv[1:] = remaining_args
SOURCE = options.source
BODY = next(node.body for node in ast.parse(SOURCE.read_text(encoding='utf-8')).body
            if isinstance(node, ast.ClassDef) and node.name == 'Driver')
METHODS = {'publish_playback', '_playback_file_stamp', '_retry_playback_off', 'run'}


class RetryCandidate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mm-off-retry-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'folder space \u05e9\u05dc\u05d5\u05dd' / 'playback.json'
        self.delays = []
        self.after_sleep = lambda: None

        async def sleep(delay):
            self.delays.append(delay)
            await asyncio.sleep(0)
            self.after_sleep()

        namespace = dict(os=os, json=json, time=time, now_ms=lambda: 123,
                         asyncio=types.SimpleNamespace(sleep=sleep, get_running_loop=asyncio.get_running_loop,
                                                       wait_for=asyncio.wait_for, TimeoutError=asyncio.TimeoutError),
                         load_token=lambda: 'fixture-not-a-credential', TokenInvalidated=ValueError)
        exec(compile(ast.Module(body=[node for node in BODY if getattr(node, 'name', None) in METHODS],
                                type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.driver = types.SimpleNamespace(PLAYBACK=str(self.path), _mic_level_or_zero=lambda: 0,
                                             player=types.SimpleNamespace(active=False))
        for name in METHODS:
            setattr(self.driver, name, types.MethodType(namespace[name], self.driver))
        self.publish = self.driver.publish_playback
        self.publish(True, 'mouth', 7)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()

    async def asyncTearDown(self):
        task = getattr(self.driver, '_pb_retry_task', None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.capture.__exit__(None, None, None)

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

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
        handle = create(str(self.path), 0x80000000, 3, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not close(handle):
                raise ctypes.WinError(ctypes.get_last_error())

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing semantics')
    async def test_native_windows_final_off_recovers_after_reader_closes(self):
        with self.windows_reader_without_delete_share():
            self.assertFalse(self.publish(False, 'mouth'))
            self.assertTrue(self.read()['on_air'], 'the real native replace must be blocked')
            pending = self.driver._pb_retry_task
            self.assertIsNotNone(pending)
        await pending
        self.assertFalse(self.read()['on_air'])
        errors = re.findall(r'winerror=(\d+)', self.output.getvalue())
        self.assertTrue(errors, self.output.getvalue())
        self.assertTrue(all(int(code) in (5, 32, 33) for code in errors), errors)

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing semantics')
    async def test_native_windows_active_tick_recovers_without_background_on_replay(self):
        with self.windows_reader_without_delete_share():
            self.assertFalse(self.publish(True, 'mouth', 88))
            self.assertEqual(self.read()['level'], 7)
            self.assertIsNone(self.driver._pb_retry_task)
        self.assertTrue(self.publish(True, 'mouth', 99))
        self.assertEqual(self.read()['level'], 99)

    async def test_final_off_recovers_without_another_cursor_tick(self):
        real_replace = os.replace
        attempts = []

        def replace(source, target):
            attempts.append(json.loads(Path(source).read_text(encoding='utf-8'))['on_air'])
            if len(attempts) == 1:
                raise PermissionError(13, 'fixture')
            return real_replace(source, target)

        with patch.object(os, 'replace', side_effect=replace):
            self.assertFalse(self.publish(False, 'mouth'))
            self.assertEqual(self.delays, [], 'foreground publication must not sleep')
            self.assertTrue(self.read()['on_air'])
            await self.driver._pb_retry_task
        self.assertEqual(attempts, [False, False])
        self.assertFalse(self.read()['on_air'])
        self.assertEqual(self.delays, [.05])

    async def test_persistent_refusal_has_five_retries_and_one_warning(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            self.publish(False, 'mouth')
            await self.driver._pb_retry_task
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(self.delays, [.05, .10, .20, .40, .80])
        self.assertEqual(self.output.getvalue().count('metadata write failed'), 1)
        self.assertTrue(self.read()['on_air'])

    async def test_newer_on_even_if_failed_invalidates_pending_off(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            self.publish(False, 'mouth')
            pending = self.driver._pb_retry_task
            self.publish(True, 'mind', 88)
            with self.assertRaises(asyncio.CancelledError):
                await pending
        self.assertEqual(replace.call_count, 2)
        self.assertIsNone(self.driver._pb_retry_task)
        self.assertTrue(self.read()['on_air'])

    async def test_many_off_calls_coalesce_to_one_pending_retry(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            tasks = []
            for _ in range(20):
                self.publish(False, 'mouth')
                tasks.append(self.driver._pb_retry_task)
            results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(sum(isinstance(result, asyncio.CancelledError) for result in results), 19)
        self.assertEqual(replace.call_count, 25)
        self.assertEqual(len(self.delays), 5)

    async def test_new_player_without_yet_publishing_cancels_old_off(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            self.publish(False, 'mouth')
            self.driver.player = types.SimpleNamespace(active=True)
            await self.driver._pb_retry_task
        self.assertEqual(replace.call_count, 1)
        self.assertTrue(self.read()['on_air'])

    async def test_same_player_reactivated_cancels_old_off(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            self.publish(False, 'mouth')
            self.driver.player.active = True
            await self.driver._pb_retry_task
        self.assertEqual(replace.call_count, 1)
        self.assertTrue(self.read()['on_air'])

    async def test_external_file_replacement_abandons_retry(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')) as replace:
            self.publish(False, 'mouth')
            self.path.write_text('{"call":"new-owner-fixture","on_air":true}', encoding='utf-8')
            await self.driver._pb_retry_task
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(self.read()['call'], 'new-owner-fixture')

    async def test_stale_generation_is_rejected_even_without_task_cancellation(self):
        fence = self.driver._playback_file_stamp()
        generation = self.driver._pb_generation
        self.publish(True, 'mind', 8)
        with patch.object(os, 'replace') as replace:
            await self.driver._retry_playback_off(generation, 'mouth', self.driver.player, fence)
        replace.assert_not_called()
        self.assertEqual(self.read()['src'], 'mind')

    async def test_shutdown_waits_for_off_retry_and_rejects_late_on(self):
        real_replace = os.replace
        remaining = 0
        late_on = []

        def replace(source, target):
            nonlocal remaining
            if remaining:
                remaining -= 1
                raise PermissionError(13, 'fixture')
            return real_replace(source, target)

        async def session(*args):
            nonlocal remaining
            self.publish(True, 'mouth', 7)
            remaining = 2

        driver = self.driver
        driver.rt = types.SimpleNamespace(spec=types.SimpleNamespace(model=types.SimpleNamespace(value='fixture')),
                                         status=object())
        driver.put = lambda *args: None
        driver.watch_commands = lambda: types.SimpleNamespace(cancel=lambda: None)
        driver.clear_liveness = lambda why: None
        driver._session = session
        self.after_sleep = lambda: late_on.append(self.publish(True, 'old-cursor', 99))
        with patch.object(os, 'replace', side_effect=replace):
            await driver.run()
        self.assertTrue(driver._pb_closing)
        self.assertEqual(late_on, [False, False])
        self.assertFalse(self.read()['on_air'])
        self.assertEqual(self.read()['src'], 'mouth')
        self.assertTrue(driver._pb_retry_task.done())

    def configure_run(self, session):
        driver = self.driver
        driver.rt = types.SimpleNamespace(spec=types.SimpleNamespace(model=types.SimpleNamespace(value='fixture')),
                                         status=object())
        driver.put = lambda *args: None
        driver.watch_commands = lambda: types.SimpleNamespace(cancel=lambda: None)
        driver.clear_liveness = lambda why: None
        driver._session = session

    async def test_late_cursor_off_cannot_cancel_the_shutdown_owned_retry(self):
        real_replace = os.replace
        remaining = 0
        late_off = []
        shutdown_tasks = []

        def replace(source, target):
            nonlocal remaining
            if remaining:
                remaining -= 1
                raise PermissionError(13, 'fixture')
            return real_replace(source, target)

        async def session(*args):
            nonlocal remaining
            self.publish(True, 'mouth', 7)
            remaining = 2

        def late_cursor():
            shutdown_tasks.append(self.driver._pb_retry_task)
            late_off.append(self.publish(False, 'old-cursor'))

        self.configure_run(session)
        self.after_sleep = late_cursor
        with patch.object(os, 'replace', side_effect=replace):
            await self.driver.run()
        self.assertEqual(late_off, [False, False])
        self.assertEqual(len(set(shutdown_tasks)), 1)
        self.assertIs(shutdown_tasks[0], self.driver._pb_retry_task)
        self.assertFalse(self.driver._pb_retry_task.cancelled())
        self.assertFalse(self.read()['on_air'])
        self.assertEqual(self.read()['src'], 'mouth')

    async def test_genuine_outer_cancellation_propagates_while_draining_shutdown(self):
        async def session(*args):
            self.publish(True, 'mouth', 7)

        self.configure_run(session)
        # A parent cancellation is different from a superseded cursor update and
        # must not be swallowed as an ordinary metadata/shutdown timeout.
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')):
            task = asyncio.create_task(self.driver.run())
            self.after_sleep = task.cancel
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(task.cancelled())
        self.assertTrue(self.driver._pb_retry_task.cancelled())

    async def test_shutdown_timeout_cancels_its_retry_without_extending_deadline(self):
        async def session(*args):
            pass

        async def blocked_sleep(delay):
            await asyncio.Event().wait()

        deadlines = []

        async def bounded_wait(awaitable, timeout):
            deadlines.append(timeout)
            # Exercise actual wait_for cancellation with a short fixture clock;
            # verify the production run requests its single two-second bound.
            return await asyncio.wait_for(awaitable, timeout=.01)

        self.configure_run(session)
        namespace = self.driver.run.__func__.__globals__
        namespace['asyncio'].sleep = blocked_sleep
        namespace['asyncio'].wait_for = bounded_wait
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')):
            await self.driver.run()
        self.assertEqual(deadlines, [2.0])
        self.assertTrue(self.driver._pb_retry_task.cancelled())
        self.assertTrue(self.read()['on_air'], 'permanent refusal stays visible as a limitation')

    async def test_successful_off_does_not_leave_cancelled_task_for_shutdown_to_await(self):
        with patch.object(os, 'replace', side_effect=PermissionError(13, 'fixture')):
            self.publish(False, 'mouth')
        old = self.driver._pb_retry_task
        self.assertTrue(self.publish(False, 'mouth'))
        self.assertIsNone(self.driver._pb_retry_task)
        with self.assertRaises(asyncio.CancelledError):
            await old
        self.assertFalse(self.read()['on_air'])


if __name__ == '__main__':
    print('Candidate source under review SHA256=' + hashlib.sha256(SOURCE.read_bytes()).hexdigest(), flush=True)
    unittest.main(verbosity=2)
