"""Detached lifecycle checks using owned synthetic children, never audio or logins."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] /
                    'candidate-supervisor-logging/mini-mouth/src/windows_launcher.py')
options, rest = parser.parse_known_args()
SOURCE = options.source.resolve()
if os.environ.get('MM_REQUIRE_WINDOWS_SUPERVISOR_TEST') == '1' and sys.platform != 'win32':
    raise RuntimeError('Required supervisor lifecycle coverage must run on actual Windows')


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # PID no longer exists.
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A just-exited detached process can await init's reap on a CI container.
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True,
                            text=True, timeout=3)
    return result.returncode == 0 and not result.stdout.strip().startswith('Z')


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Expected lifecycle transition was not observed within the deadline')


class DetachedSupervisor(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('fixture_windows_supervisor',
                                                     SOURCE.with_name('windows_supervisor.py'))
        self.supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.supervisor)
        self.temp = tempfile.TemporaryDirectory(prefix='supervisor detached שלום ')
        self.runtime = Path(self.temp.name) / 'runtime with spaces'
        self.runtime.mkdir()
        self.owned = set()
        self.parents = []
        self.addCleanup(self.cleanup)

    def read_state(self):
        row = self.supervisor.read_json(self.runtime / self.supervisor.STATE)
        if self.supervisor.valid_owner(row):
            self.owned.add(row['supervisorPid'])
            self.owned.update(pid for pid in row.get('children', {}).values()
                              if isinstance(pid, int) and pid > 0)
        return row

    def invoke(self, *args, timeout=40):
        return subprocess.run([sys.executable, '-u', str(SOURCE), *args,
                               '--runtime-dir', str(self.runtime)],
                              stdin=subprocess.DEVNULL, capture_output=True,
                              encoding='utf-8', errors='replace', timeout=timeout)

    def start(self):
        result = self.invoke('--dryrun', '--background')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        row = self.read_state()
        self.assertEqual(row['phase'], 'running', result.stdout + result.stderr)
        self.assertRegex(row['session'], r'^[a-f0-9]{32}$')
        self.assertTrue(self.supervisor.is_locked(self.runtime))
        self.assertTrue(alive(row['supervisorPid']))
        self.assertTrue(alive(row['driverPid']))
        self.assertTrue(alive(row['children']['watcher']))
        return row

    def rows(self):
        path = self.runtime / 'mini-mouth-live.log'
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('windows-launcher: '):
                try:
                    rows.append(json.loads(line.split(': ', 1)[1]))
                except ValueError:  # Writer can be midway through its current line.
                    pass
        return rows

    def stop(self, row):
        result = self.invoke('--stop', timeout=70)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stopped = self.read_state()
        self.assertEqual(stopped['session'], row['session'])
        self.assertEqual(stopped['phase'], 'stopped')
        self.assertEqual(stopped['exitCode'], 0)
        self.assertFalse(self.supervisor.is_locked(self.runtime))
        wait_for(lambda: not any(alive(pid) for pid in
                                 [row['supervisorPid'], *row['children'].values()]))
        return stopped

    def assert_still_running(self, row):
        # Give the owner several stop-file poll intervals to process a request.
        time.sleep(.4)
        current = self.read_state()
        self.assertEqual(current['session'], row['session'])
        self.assertEqual(current['phase'], 'running')
        self.assertTrue(self.supervisor.is_locked(self.runtime))
        self.assertTrue(alive(row['driverPid']))

    def cleanup(self):
        try:
            if self.supervisor.is_locked(self.runtime):
                self.invoke('--stop', timeout=70)
        finally:
            # All PIDs came from this test's private state or direct Popen. This
            # fallback is for a failing fixture, never process-name matching.
            for pid in self.owned:
                if alive(pid):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            for parent in self.parents:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=5)
            wait_for(lambda: not any(alive(pid) for pid in self.owned))
            self.temp.cleanup()

    def test_launcher_exit_reuse_and_stop_only_owned_children(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        self.parents.append(sentinel)
        first = self.start()
        # The launching Python process has exited; these PIDs remain live.
        again = self.start()
        self.assertEqual(again['session'], first['session'])
        self.assertEqual(again['supervisorPid'], first['supervisorPid'])
        self.assertEqual(again['children'], first['children'])
        self.assertEqual(len([r for r in self.rows() if r['event'] == 'child_started']), 2)
        self.stop(first)
        self.assertIsNone(sentinel.poll(), 'Scoped stop must preserve an unrelated owned fixture')

    def test_watcher_death_does_not_stop_the_driver(self):
        owner = self.start()
        os.kill(owner['children']['watcher'], signal.SIGTERM)
        wait_for(lambda: any(row['event'] == 'watcher_exit' for row in self.rows()))
        self.assert_still_running(owner)
        self.assertEqual(self.read_state()['driverPid'], owner['driverPid'])
        self.stop(owner)

    def test_stop_requires_current_generation_and_supervisor_pid(self):
        first = self.start()
        stale = {'v': 1, 'session': first['session'], 'supervisorPid': first['supervisorPid']}
        for wrong in ({**stale, 'session': '0' * 32},
                      {**stale, 'supervisorPid': first['supervisorPid'] + 1}):
            self.supervisor.write_json(self.runtime / self.supervisor.STOP, wrong)
            self.assert_still_running(first)
        self.stop(first)
        second = self.start()
        self.assertNotEqual(second['session'], first['session'])
        self.supervisor.write_json(self.runtime / self.supervisor.STOP, stale)
        self.assert_still_running(second)
        self.stop(second)

    def test_unlocked_stale_state_refuses_start_or_pid_based_stop(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        self.parents.append(sentinel)
        stale = {'v': 1, 'session': 'a' * 32, 'supervisorPid': sentinel.pid,
                 'driverPid': sentinel.pid, 'children': {'driver': sentinel.pid}, 'phase': 'running'}
        self.supervisor.write_json(self.runtime / self.supervisor.STATE, stale)
        result = self.invoke('--stop')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('No PID was killed from stale state', result.stderr)
        result = self.invoke('--dryrun', '--background')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('previous supervisor disappeared', result.stderr)
        self.assertIsNone(sentinel.poll())
        self.assertEqual(self.supervisor.read_json(self.runtime / self.supervisor.STATE), stale)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires an actual Windows console window')
    def test_closing_the_launch_console_preserves_the_detached_call(self):
        import ctypes
        from ctypes import wintypes
        marker = self.runtime / 'console-wrapper.json'
        wrapper = self.runtime / 'console-wrapper.py'
        wrapper.write_text('''import ctypes, json, pathlib, subprocess, sys, time
from ctypes import wintypes
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetConsoleWindow.restype = wintypes.HWND
with open(sys.argv[3] + '.log', 'wb') as output:
    result = subprocess.run([sys.executable, '-u', sys.argv[1], '--dryrun', '--background',
                             '--runtime-dir', sys.argv[2]], stdin=subprocess.DEVNULL,
                            stdout=output, stderr=output)
pathlib.Path(sys.argv[3]).write_text(json.dumps({'exitCode': result.returncode,
                                              'hwnd': kernel.GetConsoleWindow()}))
time.sleep(120)
''', encoding='utf-8')
        wrapper_process = subprocess.Popen([sys.executable, str(wrapper), str(SOURCE),
                                            str(self.runtime), str(marker)],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.parents.append(wrapper_process)
        record = wait_for(lambda: self.supervisor.read_json(marker), timeout=40)
        owner = self.read_state()
        self.assertEqual(record['exitCode'], 0)
        self.assertTrue(record['hwnd'], 'The actual Windows console fixture must expose its own window')
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.PostMessageW.restype = wintypes.BOOL
        self.assertTrue(user.PostMessageW(record['hwnd'], 0x0010, 0, 0))  # WM_CLOSE, owned window only.
        wrapper_process.wait(timeout=15)
        self.assert_still_running(owner)
        self.stop(owner)


class RestartStopRace(unittest.TestCase):
    def test_hard_driver_exit_does_not_claim_descendant_cleanup(self):
        sys.path.insert(0, str(SOURCE.parent))
        self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        spec = importlib.util.spec_from_file_location('descendant_fixture_launcher', SOURCE)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        spec = importlib.util.spec_from_file_location('descendant_fixture_owner', SOURCE.with_name('windows_supervisor.py'))
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        with tempfile.TemporaryDirectory(prefix='supervisor descendant שלום ') as box:
            runtime = Path(box)
            marker = runtime / 'owned-descendant.pid'
            owner = supervisor.Owner(runtime, 'c' * 32)
            children = []
            original_popen = subprocess.Popen
            descendant = None

            def spawn_fixture(arguments, **kwargs):
                # Let subprocess.run use real native cleanup (not a Python emitter).
                if arguments[0] != sys.executable:
                    return original_popen(arguments, **kwargs)
                if not children:
                    script = ('import os,pathlib,subprocess,sys,time; '
                              "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
                              'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                              f'pathlib.Path({str(marker)!r}).write_text(str(p.pid)); '
                              'time.sleep(.15); os._exit(9)')
                else:
                    script = 'import time; time.sleep(120)'
                proc = original_popen([sys.executable, '-u', '-c', script], **kwargs)
                children.append(proc)
                return proc

            try:
                with patch.object(launcher.subprocess, 'Popen', spawn_fixture), \
                     contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    result = launcher.main(['--dryrun', '--duration', '3', '--runtime-dir', str(runtime)], owner=owner)
                owner.finish(result)
                descendant = int(marker.read_text())
                self.assertNotEqual(result, 0)
                self.assertEqual(owner.state['phase'], 'failed')
                self.assertFalse(alive(descendant) and owner.state['cleanupComplete'],
                                 'A surviving descendant makes completed cleanup a false claim')
                if not owner.state['cleanupComplete']:
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertNotEqual(supervisor.start(runtime, dryrun=True), 0,
                                            'Unconfirmed previous children must block another call')
            finally:
                if descendant is None and marker.exists():
                    descendant = int(marker.read_text())
                if descendant and alive(descendant):
                    os.kill(descendant, signal.SIGTERM)
                    wait_for(lambda: not alive(descendant))
                for proc in children:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=5)

    def test_stop_arriving_during_restart_validation_is_a_clean_stop(self):
        sys.path.insert(0, str(SOURCE.parent))
        self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        spec = importlib.util.spec_from_file_location('race_fixture_launcher', SOURCE)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        spec = importlib.util.spec_from_file_location('race_fixture_owner', SOURCE.with_name('windows_supervisor.py'))
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        with tempfile.TemporaryDirectory(prefix='supervisor restart race שלום ') as box:
            runtime = Path(box)
            owner = supervisor.Owner(runtime, 'b' * 32)
            children = []
            original_popen = subprocess.Popen
            original_validation = owner.restart_crashes
            stop_injected = False

            def spawn_fixture(arguments, **kwargs):
                # Let subprocess.run use real native cleanup (not a Python emitter).
                if arguments[0] != sys.executable:
                    return original_popen(arguments, **kwargs)
                if not children:
                    script = ('import time; time.sleep(.15); '
                              'from windows_supervisor import request_restart; '
                              'request_restart([time.time()]); raise SystemExit(75)')
                else:
                    script = 'import time; time.sleep(120)'
                kwargs['env'] = dict(kwargs['env'], PYTHONPATH=str(SOURCE.parent))
                proc = original_popen([sys.executable, '-u', '-c', script], **kwargs)
                children.append(proc)
                return proc

            def stop_during_validation(proc):
                nonlocal stop_injected
                crashes = original_validation(proc)
                if crashes is not None:
                    supervisor.write_json(runtime / supervisor.STOP,
                                          {'v': 1, 'session': owner.state['session'],
                                           'supervisorPid': owner.state['supervisorPid']})
                    stop_injected = True
                return crashes

            try:
                with patch.object(launcher.subprocess, 'Popen', spawn_fixture), \
                     patch.object(owner, 'restart_crashes', stop_during_validation), \
                     contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    result = launcher.main(['--dryrun', '--duration', '3', '--runtime-dir', str(runtime)], owner=owner)
                self.assertTrue(stop_injected, 'The real child must reach validated restart handoff')
                self.assertEqual(result, 0, 'An owner stop arriving during handoff must not become failure75')
                self.assertEqual(len(children), 2, 'No replacement may start after the stop was observed')
                self.assertTrue(all(proc.poll() is not None for proc in children))
                owner.finish(result)
                self.assertEqual(owner.state['phase'], 'stopped')
                self.assertNotIn('"event": "driver_restart"', (runtime / 'mini-mouth-live.log').read_text())
            finally:
                for proc in children:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
