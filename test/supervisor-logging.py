"""Real owned-child lifecycle fixtures; dryrun prevents graph/audio/credential access."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'candidate-supervisor-logging/mini-mouth/src/windows_launcher.py')
options, rest = parser.parse_known_args()


class SupervisorLogging(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('fixture_launcher', options.source)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        self.temp = tempfile.TemporaryDirectory(prefix='supervisor fixture שלום ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.children = []
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def run_case(self, role=None, code=0, interrupt=False):
        popen = subprocess.Popen
        sleeper = self.launcher.time.sleep
        def start(arguments, **kwargs):
            index = len(self.children)
            exits = role is not None and index == (0 if role == 'driver' else 1)
            script = f'import time; time.sleep({0.15 if exits else 30}); raise SystemExit({code})'
            child = popen([sys.executable, '-u', '-c', script], **kwargs)
            self.children.append(child)
            return child

        interrupted = False
        def sleep(seconds):
            nonlocal interrupted
            if interrupt and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            sleeper(seconds)

        out, err = io.StringIO(), io.StringIO()
        with patch.object(self.launcher.subprocess, 'Popen', start), patch.object(self.launcher.time, 'sleep', sleep), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = self.launcher.main(['--dryrun', '--duration', '1', '--runtime-dir', str(self.root)])
        self.assertEqual(len(self.children), 2)
        self.assertTrue(all(child.poll() is not None for child in self.children))
        rows = [json.loads(line.split(': ', 1)[1]) for line in (self.root / 'mini-mouth-live.log').read_text(encoding='utf-8').splitlines() if line.startswith('windows-launcher: ')]
        self.assertEqual([r['role'] for r in rows if r['event'] == 'child_started'], ['driver', 'watcher'])
        self.assertEqual([r['role'] for r in rows if r['event'] == 'child_stopped'], ['watcher', 'driver'])
        self.assertEqual(rows[-1]['event'], 'supervisor_exit')
        self.assertEqual(rows[-1]['exit_code'], result)
        self.assertTrue(all('at' in row and 'supervisor_pid' in row for row in rows))
        return result, rows, err.getvalue()

    def test_watcher_zero_exit_records_cleanup_reason(self):
        result, rows, stderr = self.run_case('watcher', 0)
        self.assertEqual(result, 0)
        self.assertEqual(next(r['exit_code'] for r in rows if r['event'] == 'watcher_exit'), 0)
        self.assertTrue(next(r['was_running'] for r in rows if r['event'] == 'child_stopped' and r['role'] == 'driver'))
        self.assertIn('watcher stopped (0)', stderr)

    def test_watcher_failure_keeps_exact_exit_code(self):
        result, rows, stderr = self.run_case('watcher', 7)
        self.assertEqual(result, 7)
        self.assertEqual(next(r['exit_code'] for r in rows if r['event'] == 'watcher_exit'), 7)

    def test_driver_zero_is_logged_separately_from_unexpected_stop_status(self):
        result, rows, stderr = self.run_case('driver', 0)
        self.assertEqual(result, 1)
        self.assertEqual(next(r['exit_code'] for r in rows if r['event'] == 'driver_exit'), 0)
        self.assertIn('child exit 0; supervisor exit 1', stderr)

    def test_driver_failure_keeps_exact_exit_code(self):
        result, rows, stderr = self.run_case('driver', 9)
        self.assertEqual(result, 9)
        self.assertEqual(next(r['exit_code'] for r in rows if r['event'] == 'driver_exit'), 9)

    def test_intentional_interrupt_is_logged_and_successful(self):
        result, rows, stderr = self.run_case(interrupt=True)
        self.assertEqual(result, 0)
        self.assertTrue(any(r['event'] == 'interrupted' for r in rows))

    def test_bounded_dryrun_logs_deliberate_end(self):
        result, rows, stderr = self.run_case()
        self.assertEqual(result, 0)
        self.assertTrue(any(r['event'] == 'duration_elapsed' for r in rows))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
