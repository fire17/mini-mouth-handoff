#!/usr/bin/env python3
"""Actual wrapper tests; every source and receipt lives in an isolated temp tree."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import venv

parser = argparse.ArgumentParser()
parser.add_argument('--shell', required=True, choices=['bash', 'pwsh', 'powershell.exe'])
options, rest = parser.parse_known_args()
SHELL = shutil.which(options.shell)
if not SHELL:
    parser.error(f'required actual shell is unavailable: {options.shell}')
ROOT = Path(__file__).resolve().parents[1]


class Monitor:
    def __init__(self, case):
        self.case = case
        self.lines = []
        self.error = None
        self.proc = subprocess.Popen(case.command(), cwd=case.directory, env=case.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=os.name != 'nt',
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        case.addCleanup(self.stop)

    def read(self):
        try:
            for line in iter(self.proc.stdout.readline, b''):
                self.lines.append(line.decode('utf-8', 'strict').rstrip('\r\n'))
        except Exception as error:
            self.error = error

    def wait(self, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error:
                raise self.error
            if predicate(self.lines):
                return
            if self.proc.poll() is not None:
                raise AssertionError(f'monitor exited {self.proc.returncode}: {self.lines!r}')
            time.sleep(0.02)
        raise AssertionError(f'monitor output timed out: {self.lines!r}')

    def armed(self):
        self.wait(lambda lines: all(any(f'EAR ARMED {ear}' in line for line in lines)
            for ear in ('user-inputs', 'system')))
        # The monitor is a lasting stream, not just a successful plan command.
        time.sleep(0.3)
        self.case.assertIsNone(self.proc.poll())

    def stop(self):
        if self.proc.poll() is None:
            if os.name == 'nt':
                result = subprocess.run(['taskkill.exe', '/PID', str(self.proc.pid), '/T', '/F'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                self.case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
        self.proc.wait(timeout=10)
        self.reader.join(timeout=5)
        self.case.assertFalse(self.reader.is_alive(), 'owned stdout writers did not close after process-tree cleanup')
        self.proc.stdout.close()


class EarWrapper(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ear wrapper שלום ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.lite = self.directory / 'livemind-lite'
        self.lite.mkdir()
        for name in ('lm-ear', 'lm-ear.ps1', 'mm-ear.py'):
            shutil.copy2(ROOT / 'livemind-lite' / name, self.lite / name)
        self.log = self.directory / 'temporary live log.log'
        self.pidfile = self.directory / 'temporary driver.pid'
        self.log.write_text('🗣 seed-spoken שלום🐙\n🗣⌨ seed-typed\n🗣⌨ [from MagicUI] seed-magic\n'
            '=== driver seed-system ===\n=== Windows launcher seed-windows ===\n'
            '⚠ error seed-error\n👄 seed-mouth-MUST-NOT-APPEAR\n', encoding='utf-8')
        self.pidfile.write_text('12345\n', encoding='utf-8')
        config = {'version': 3, 'me': 'mind', 'ears': {
            'user-inputs': {'enabled': True, 'log': str(self.log), 'typed': None, 'om': None},
            'system': {'enabled': True, 'log': str(self.log), 'pidfile': str(self.pidfile)},
            'board': {'enabled': False, 'docs': str(self.directory / 'unused board')},
            'bus': {'enabled': False, 'bus': str(self.directory / 'unused bus')},
        }}
        config_path = self.directory / 'temporary ears.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        self.seen = self.directory / 'temporary seen'
        self.env = dict(os.environ, LM_EARS=str(config_path), LM_EAR_SEEN_DIR=str(self.seen),
            LM_EAR_PROFILE='mind', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')

    def command(self, *args):
        if options.shell == 'bash':
            return [SHELL, str(self.lite / 'lm-ear'), *args]
        return [SHELL, '-NoLogo', '-NoProfile', '-NonInteractive',
            '-File', str(self.lite / 'lm-ear.ps1'), *args]

    def run_wrapper(self, *args):
        return subprocess.run(self.command(*args), cwd=self.directory, env=self.env,
            capture_output=True, encoding='utf-8', errors='strict', timeout=45)

    def append(self, data):
        with self.log.open('ab') as output:
            output.write(data)
            output.flush()

    def test_selftest_filters_actual_utf8_sources(self):
        result = self.run_wrapper('--selftest')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for text in ('[Spoken] you: seed-spoken שלום🐙', '[Typed ⌨] you: seed-typed',
                     '[from MagicUI] you: seed-magic', '[Driver] === driver seed-system',
                     '[Driver] === Windows launcher seed-windows', '[Error] ⚠ error seed-error'):
            self.assertIn(text, result.stdout)
        self.assertNotIn('seed-mouth-MUST-NOT-APPEAR', result.stdout)
        self.assertFalse(self.seen.exists(), 'selftest does not stamp or arm an ear')

    def test_json_plan_and_exit_codes(self):
        result = self.run_wrapper('--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual([row['ear'] for row in plan], ['user-inputs', 'system'])
        self.assertTrue(all(row['persistent'] for row in plan))
        filtered = self.run_wrapper('--json', '--only', 'user-inputs')
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        self.assertEqual([row['ear'] for row in json.loads(filtered.stdout)], ['user-inputs'])
        self.assertEqual(self.run_wrapper('not-an-ear').returncode, 2)
        self.assertEqual(self.run_wrapper('--profile').returncode, 2)
        self.log.write_text('👄 mouth-only-MUST-NOT-APPEAR\n', encoding='utf-8')
        quiet = self.run_wrapper('--selftest')
        self.assertEqual(quiet.returncode, 1, quiet.stderr + quiet.stdout)
        self.assertNotIn('mouth-only-MUST-NOT-APPEAR', quiet.stdout)

    def test_no_arguments_stays_alive_and_delivers_new_events(self):
        monitor = Monitor(self)
        monitor.armed()
        self.append('🗣 live-spoken שלום🐙\n🗣⌨ live-typed\n=== Windows launcher live-system ===\n'
                    '⚠ error live-error\n👄 live-mouth-MUST-NOT-APPEAR\n'.encode('utf-8'))
        monitor.wait(lambda lines: all(any(text in line for line in lines)
            for text in ('live-spoken שלום🐙', 'live-typed', 'live-system', 'live-error')), timeout=8)
        self.assertFalse(any('live-mouth-MUST-NOT-APPEAR' in line for line in monitor.lines))
        self.pidfile.write_text('67890\n', encoding='utf-8')
        monitor.wait(lambda lines: any('MINI-MOUTH DRIVER CHANGED 12345 -> 67890' in line for line in lines), timeout=5)
        self.assertTrue((self.seen / 'mind.user-inputs.json').is_file())
        self.assertTrue((self.seen / 'mind.system.json').is_file())
        for receipt in self.seen.glob('*.json'):
            value = json.loads(receipt.read_text(encoding='utf-8'))
            self.assertTrue(all(Path(path).is_relative_to(self.directory) for path in value['pos']))
        self.assertIsNone(monitor.proc.poll())

    def test_partial_utf8_is_delivered_once_only_after_the_newline(self):
        monitor = Monitor(self)
        monitor.armed()
        payload = '🗣 split-byte-proof שלום🐙\n'.encode('utf-8')
        self.append(payload[:2])
        time.sleep(0.35)
        self.append(payload[2:-2])
        time.sleep(0.35)
        self.assertFalse(any('split-byte-proof' in line for line in monitor.lines), 'an incomplete line was emitted')
        self.append(payload[-2:])
        monitor.wait(lambda lines: any('[Spoken] you: split-byte-proof שלום🐙' in line for line in lines), timeout=5)
        time.sleep(0.3)
        self.assertEqual(sum('split-byte-proof' in line for line in monitor.lines), 1)
        self.assertFalse(any('\ufffd' in line for line in monitor.lines))
        self.log.write_text('🗣 after-truncation\n', encoding='utf-8')
        monitor.wait(lambda lines: any('[Spoken] you: after-truncation' in line for line in lines), timeout=5)

    def test_bundle_virtualenv_preferred_and_native_exit_preserved(self):
        prefix = self.directory / 'mini-mouth' / '.venv'
        venv.EnvBuilder(with_pip=False, symlinks=os.name != 'nt').create(prefix)
        if os.name != 'nt' and options.shell != 'bash':
            # Exercise the Windows wrapper's bundled layout with a real local
            # interpreter; actual Windows CI uses the native venv Scripts tree.
            (prefix / 'Scripts').mkdir()
            (prefix / 'Scripts' / 'python.exe').symlink_to(prefix / 'bin' / 'python')
        (self.lite / 'mm-ear.py').write_text(
            "import json, sys\nprint(json.dumps({'prefix':sys.prefix,'args':sys.argv[1:]}))\nsys.exit(7)\n", encoding='utf-8')
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 7, result.stderr + result.stdout)
        receipt = json.loads(result.stdout)
        self.assertEqual(os.path.normcase(str(Path(receipt['prefix']).resolve())), os.path.normcase(str(prefix.resolve())))
        self.assertEqual(receipt['args'], ['all'])

    @unittest.skipIf(options.shell == 'bash', 'Windows wrapper interpreter discovery')
    def test_missing_interpreter_is_a_nonzero_failure(self):
        empty_path = self.directory / 'empty executable search path'
        empty_path.mkdir()
        result = subprocess.run(self.command('--json'), cwd=self.directory,
            env=dict(self.env, PATH=str(empty_path)), capture_output=True,
            encoding='utf-8', errors='strict', timeout=45)
        self.assertEqual(result.returncode, 127, result.stderr + result.stdout)
        self.assertIn('Python is missing', result.stderr)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
