"""Run the whole TUI against real in-memory XO, without devices or live services.

This proves imports, history rendering and two seconds of main-loop progress.
It does not prove physical keyboard input, resize events or terminal glyph quality.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--bundle', type=Path, required=True)
opts, rest = parser.parse_known_args()
sys.argv[1:] = rest
BUNDLE = opts.bundle.resolve()

WRAPPER = r'''
import json, os, pathlib, runpy, socket, sys, time
root, home = map(pathlib.Path, sys.argv[1:3])
pathlib.Path.home = classmethod(lambda cls: home)
original_expanduser = os.path.expanduser
os.path.expanduser = lambda value: str(home / value[2:]) if value.startswith('~/') else original_expanduser(value)
sys.path[:0] = [str(root/'XO/src'), str(root/'mini-mouth/src'), str(root/'mini-mouth')]
os.environ.update(MM_NAMESPACE='fixture-tui-startup', MM_NO_LAYOUT='1', MM_HISTORY='10', MM_RTL='0')
def deny_connection(*args, **kwargs):
    raise RuntimeError('Fixture prohibits network connections')
socket.socket.connect = deny_connection
socket.socket.connect_ex = deny_connection
from xomouth import Mouth
mouth = Mouth(namespace='fixture-tui-startup')
record = mouth.rt.conv.entries['fixture-user']
record.kind = 'user'
record.text = 'fixture hello שלום'
record.at = 1000
record.time = '00:00:01'
Mouth.live = classmethod(lambda cls, **kwargs: mouth)
tui = root/'mini-mouth/tui.py'
source = tui.read_text(encoding='utf-8-sig')
import ast
tree = ast.parse(source)
main_loop = next(node for node in reversed(tree.body) if isinstance(node, ast.While))
tick_line = main_loop.body[0].lineno
ticks, started = 0, None
def trace(frame, event, arg):
    global ticks, started
    if event == 'line' and frame.f_code.co_filename == str(tui) and frame.f_lineno == tick_line:
        ticks += 1
        if started is None:
            started = time.monotonic()
            assert frame.f_globals['typed_editor']() is not None, 'Actual line editor imports must succeed'
            print('TUI_FIXTURE_MAIN_LOOP_ENTERED', flush=True)
        if time.monotonic() - started >= 2:
            sys.settrace(None)
            frame.f_globals['LOOP']['done'] = True
            frame.f_globals['sub'].cancel()
            frame.f_globals['teardown_bar']()
            frame.f_globals['restore_tty']()
            print('TUI_FIXTURE_RESULT=' + json.dumps({'ticks': ticks, 'seconds': time.monotonic()-started}), flush=True)
            raise SystemExit(0)
    return trace
sys.settrace(trace)
runpy.run_path(str(tui), run_name='__main__')
'''


class Startup(unittest.TestCase):
    def run_shell(self, shell=None):
        with tempfile.TemporaryDirectory(prefix='tui-startup-fixture-') as folder:
            temp = Path(folder)
            wrapper = temp/'fixture runner.py'
            wrapper.write_text(textwrap.dedent(WRAPPER), encoding='utf-8')
            home = temp/'isolated home'
            home.mkdir()
            env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
            if shell:
                quote = lambda text: "'" + str(text).replace("'", "''") + "'"
                ps = temp/'run fixture.ps1'
                ps.write_text(
                    "$ErrorActionPreference='Stop'\n"
                    "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)\n" +
                    '& ' + ' '.join(map(quote, [sys.executable, wrapper, BUNDLE, home])) + '\n' +
                    'if ($global:LASTEXITCODE -ne 0) { exit $global:LASTEXITCODE }\n' +
                    "Write-Output 'TUI_FIXTURE_SHELL_RETURNED'\n", encoding='utf-8-sig')
                cmd = [shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(ps)]
                if Path(shell).name.lower() == 'powershell.exe':
                    env = {k:v for k,v in env.items() if k.upper() != 'PSMODULEPATH'}
            else:
                cmd = [sys.executable, str(wrapper), str(BUNDLE), str(home)]
            result = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=15)
            output = result.stdout.decode('utf-8', errors='replace')
            errors = result.stderr.decode('utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, output[-3000:] + errors)
            self.assertNotIn('Traceback', errors)
            self.assertIn('fixture hello', output)
            self.assertIn('TUI_FIXTURE_MAIN_LOOP_ENTERED', output)
            line = next(line.split('TUI_FIXTURE_RESULT=',1)[1] for line in output.splitlines() if 'TUI_FIXTURE_RESULT=' in line)
            receipt = json.loads(line)
            self.assertGreaterEqual(receipt['seconds'], 2)
            self.assertGreater(receipt['ticks'], 2)
            if shell:
                self.assertIn('TUI_FIXTURE_SHELL_RETURNED', output)
            print(json.dumps({'shell': shell or 'python', **receipt}), flush=True)

    def test_native_python_complete_tui_startup(self):
        self.run_shell()

    @unittest.skipUnless(sys.platform == 'win32', 'actual Windows PowerShell required')
    def test_windows_powershell_51_complete_tui_startup(self):
        shell = shutil.which('powershell.exe')
        self.assertIsNotNone(shell)
        self.run_shell(shell)

    @unittest.skipUnless(sys.platform == 'win32', 'actual Windows PowerShell required')
    def test_windows_powershell_7_complete_tui_startup(self):
        shell = shutil.which('pwsh.exe')
        self.assertIsNotNone(shell)
        self.run_shell(shell)


if __name__ == '__main__':
    if os.environ.get('MM_REQUIRE_WINDOWS_TUI_TEST') == '1' and sys.platform != 'win32':
        raise SystemExit('Required actual Windows platform unavailable')
    unittest.main(verbosity=2)
