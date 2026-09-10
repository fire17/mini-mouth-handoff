"""Session-scoped graceful stop and bounded owned-process fallback, no live imports."""
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
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'candidate-supervisor-logging/mini-mouth')
options, rest = parser.parse_known_args()
ROOT = options.source.resolve()
sys.path.insert(0, str(ROOT / 'src'))
import windows_launcher as launcher
import windows_supervisor as supervisor


class CooperativeStop(unittest.TestCase):
    def test_matching_stop_runs_driver_finally_and_seals_actual_tap(self):
        with tempfile.TemporaryDirectory(prefix='cooperative stop שלום ') as box:
            directory = Path(box)
            marker = directory / 'playing.json'
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                       MM_WINDOWS_SUPERVISOR_SESSION='a' * 32, MM_WINDOWS_SUPERVISOR_PID=str(os.getpid()),
                       MM_WINDOWS_SUPERVISOR_RESTART_PATH=str(directory / supervisor.RESTART), MM_RESUME_CRASHES='')
            prefix = '''
import asyncio, json as _json, os as actualos, sys, time as _time, types
from pathlib import Path
os = types.SimpleNamespace(**{name: getattr(actualos, name) for name in dir(actualos)})
os.name = 'nt'
__file__ = 'fixture-live.py'
directory = Path(BOX)
sys.modules['live_wall'] = types.SimpleNamespace(surface=lambda _: str(directory / 'tap'))
from tap_log import TapLog
sub = types.SimpleNamespace(cancel=lambda: None)
mouth = types.SimpleNamespace(write=lambda fn: None)
class Driver:
    def __init__(self, mouth):
        self.commands = asyncio.Queue()
        self.tap = TapLog(root=str(directory / 'tap'), link_dir=str(directory / 'links'))
        self.tap.open()
    async def run(self):
        Path(MARKER).write_text(_json.dumps({'playing': True}))
        try:
            command = await self.commands.get()
            assert command == ('stop', None)
        finally:
            await asyncio.sleep(.05)
            Path(MARKER).write_text(_json.dumps({'playing': False}))
            self.tap.event('fixture_stop_finally')
'''.replace('BOX', repr(box)).replace('MARKER', repr(str(marker)))
            source = (ROOT / 'live.py').read_text(encoding='utf-8')
            child = subprocess.Popen([sys.executable, '-u', '-c', prefix + source[source.index('crashes = [float(t)'):]],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(marker.exists())
                supervisor.write_json(directory / supervisor.STOP, {'v': 1, 'session': 'b'*32, 'supervisorPid': os.getpid()})
                time.sleep(.3)
                self.assertIsNone(child.poll(), 'A different session cannot stop this driver')
                supervisor.write_json(directory / supervisor.STOP, {'v': 1, 'session': 'a'*32, 'supervisorPid': os.getpid()})
                out, err = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, out + err)
                self.assertIn('local supervisor stop requested', out)
                self.assertFalse(json.loads(marker.read_text())['playing'])
                rows = [json.loads(line) for line in (directory / 'tap' / f'livemind-{child.pid}.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual([row['ev'] for row in rows], ['run', 'fixture_stop_finally', 'run_end'])
                self.assertFalse((directory / 'links' / f'livemind-{child.pid}.jsonl').exists())
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)

    def test_unresponsive_driver_gets_bounded_grace_then_owned_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='cooperative timeout שלום ') as box:
            directory = Path(box)
            owner = supervisor.Owner(directory, 'c' * 32)
            children = []
            popen = subprocess.Popen
            def start(arguments, **kwargs):
                index = len(children)
                if index == 0:
                    script = ('import time; from windows_supervisor import write_json; '
                              'time.sleep(.15); '
                              f"write_json({str(directory / supervisor.STOP)!r}, "
                              f"{{'v':1,'session':{'c'*32!r},'supervisorPid':{os.getpid()}}}); "
                              'time.sleep(120)')
                else:
                    script = 'import time; time.sleep(120)'
                kwargs['env'] = dict(kwargs['env'], PYTHONPATH=str(ROOT / 'src'))
                child = popen([sys.executable, '-u', '-c', script], **kwargs)
                children.append(child)
                return child
            began = time.monotonic()
            try:
                with patch.object(launcher.subprocess, 'Popen', start), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = launcher.main(['--dryrun', '--duration', '20', '--runtime-dir', box], owner=owner)
                elapsed = time.monotonic() - began
                self.assertEqual(code, 0)
                self.assertGreaterEqual(elapsed, supervisor.STOP_GRACE_SECONDS)
                self.assertLess(elapsed, supervisor.STOP_GRACE_SECONDS + 15)
                self.assertTrue(all(proc.poll() is not None for proc in children))
                log = (directory / 'mini-mouth-live.log').read_text(encoding='utf-8')
                self.assertIn('"event": "cooperative_stop_timeout"', log)
                self.assertNotIn('"event": "cooperative_stop_complete"', log)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
