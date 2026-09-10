"""Actual lifecycle block and owned disposable children; no live driver imports."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'candidate-supervisor-logging/mini-mouth')
options, rest = parser.parse_known_args()
ROOT = options.source.resolve()
sys.path.insert(0, str(ROOT / 'src'))
import windows_launcher as launcher
import windows_supervisor as supervisor


class LifecycleExit(unittest.TestCase):
    def run_lifecycle(self, statement, *, windows=False, previous=0):
        with tempfile.TemporaryDirectory(prefix='resume lifecycle שלום ') as box:
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       MM_WINDOWS_SUPERVISOR_SESSION='a' * 32, MM_WINDOWS_SUPERVISOR_PID='1234',
                       MM_WINDOWS_SUPERVISOR_RESTART_PATH=str(Path(box) / 'restart.json'),
                       MM_RESUME_CRASHES=','.join(str(time.time()) for _ in range(previous)))
            prefix = '''
import asyncio, json as _json, os as actualos, sys, time as _time, types
os = types.SimpleNamespace(**{name: getattr(actualos, name) for name in dir(actualos)})
os.name = PLATFORM
__file__ = 'fixture-live.py'
sub = types.SimpleNamespace(cancel=lambda: None)
mouth = types.SimpleNamespace(write=lambda fn: None)
def sleep(seconds): print('FIXTURE_BACKOFF', seconds, flush=True)
_time.sleep = sleep
def fail_exec(*args): raise OSError('fixture exec failed')
os.execve = fail_exec
class Driver:
    def __init__(self, mouth): pass
    async def run(self):
        STATEMENT
'''.replace('PLATFORM', repr('nt' if windows else 'posix')).replace('STATEMENT', statement)
            source = (ROOT / 'live.py').read_text(encoding='utf-8')
            lifecycle = source[source.index('crashes = [float(t)'):]
            child = subprocess.run([sys.executable, '-u', '-c', prefix + lifecycle], env=env,
                                   capture_output=True, text=True, encoding='utf-8', timeout=10)
            metadata = supervisor.read_json(Path(box) / 'restart.json')
            return child, metadata

    def test_intentional_stops_preserve_success(self):
        for statement in ('return', 'raise SystemExit(0)', 'raise KeyboardInterrupt()'):
            with self.subTest(statement=statement):
                child, metadata = self.run_lifecycle(statement)
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertIsNone(metadata)

    def test_fatal_exits_keep_visible_failure(self):
        for statement, code, diagnostic in (
            ("raise SystemExit('fixture credential expired')", 1, 'fixture credential expired'),
            ('raise SystemExit(3)', 3, 'driver exit: 3'),
            ('raise asyncio.CancelledError()', 1, 'CancelledError'),
            ("raise RuntimeError('fixture socket closed')", 1, 'fixture exec failed'),
        ):
            with self.subTest(statement=statement):
                child, metadata = self.run_lifecycle(statement)
                self.assertEqual(child.returncode, code, child.stderr)
                self.assertIn(diagnostic, child.stderr)
                self.assertIsNone(metadata)

    def test_windows_resume_is_bound_and_retains_existing_backoff(self):
        for previous, backoff in ((0, 2), (4, 60)):
            with self.subTest(previous=previous):
                child, row = self.run_lifecycle("raise RuntimeError('fixture socket closed')", windows=True, previous=previous)
                self.assertEqual(child.returncode, 75, child.stderr)
                self.assertIn(f'FIXTURE_BACKOFF {backoff}', child.stdout)
                self.assertEqual(row['session'], 'a' * 32)
                self.assertGreater(row['driverPid'], 0)
                self.assertEqual(len(row['crashes']), previous + 1)
                self.assertNotIn('fixture exec failed', child.stderr)


class OwnedRestart(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='owned restart שלום ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = supervisor.Owner(self.root, 'b' * 32)
        self.children = []
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for proc in self.children:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)

    def test_restart_metadata_rejects_stale_or_invalid_claims(self):
        proc = types.SimpleNamespace(pid=1234, returncode=75)
        good = {'v': 1, 'session': self.owner.state['session'], 'driverPid': proc.pid, 'crashes': [time.time()]}
        for changed in ({'session': 'c'*32}, {'driverPid': 5678}, {'crashes': [time.time()-200]},
                        {'crashes': [float('nan')]}, {'crashes': [True]}, {'crashes': []}):
            with self.subTest(changed=changed):
                supervisor.write_json(self.root / supervisor.RESTART, {**good, **changed})
                self.assertIsNone(self.owner.restart_crashes(proc))
        supervisor.write_json(self.root / supervisor.RESTART, good)
        self.assertEqual(self.owner.restart_crashes(proc), good['crashes'])
        proc.returncode = 1
        self.assertIsNone(self.owner.restart_crashes(proc))

    def run_owned(self, *, metadata, stop_before_restart=False):
        popen = subprocess.Popen
        launches = []
        def start(arguments, **kwargs):
            index = len(self.children)
            if index == 0:
                script = 'import os, time; time.sleep(.15); '
                if metadata:
                    script += "from windows_supervisor import request_restart; request_restart([time.time()]); "
                if stop_before_restart:
                    script += ("from windows_supervisor import write_json; "
                               f"write_json({str(self.root / supervisor.STOP)!r}, "
                               f"{{'v':1,'session':{'b'*32!r},'supervisorPid':{os.getpid()}}}); ")
                script += 'raise SystemExit(75)'
            else:
                script = 'import time; time.sleep(30)'
            kwargs['env'] = dict(kwargs['env'], PYTHONPATH=str(ROOT / 'src'))
            proc = popen([sys.executable, '-u', '-c', script], **kwargs)
            self.children.append(proc)
            launches.append(kwargs['env'].get('MM_RESUME_CRASHES'))
            return proc

        original_stop = self.owner.stop_requested
        def requested():
            return original_stop() or len(self.children) >= 3

        with patch.object(launcher.subprocess, 'Popen', start), patch.object(self.owner, 'stop_requested', requested), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = launcher.main(['--dryrun', '--duration', '3', '--runtime-dir', str(self.root)], owner=self.owner)
        self.assertTrue(all(proc.poll() is not None for proc in self.children))
        return result, launches

    def test_valid_handoff_starts_new_owned_pid_and_preserves_crash_window(self):
        result, launches = self.run_owned(metadata=True)
        self.assertEqual(result, 0)
        self.assertEqual(len(self.children), 3, 'one watcher, first driver and one replacement')
        self.assertNotEqual(self.children[0].pid, self.children[2].pid)
        self.assertEqual(self.owner.state['driverPid'], self.children[2].pid)
        self.assertTrue(launches[2])

    def test_bare_reserved_exit_does_not_request_restart(self):
        result, _ = self.run_owned(metadata=False)
        self.assertEqual(result, 75)
        self.assertEqual(len(self.children), 2)

    def test_owner_stop_prevents_pending_restart(self):
        result, _ = self.run_owned(metadata=True, stop_before_restart=True)
        self.assertEqual(result, 0)
        self.assertEqual(len(self.children), 2)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
