"""Non-live mic-signal diagnostics: real synthetic children and pure gate fixtures."""
import argparse
import asyncio
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path,
                    default=ROOT / 'candidate-mic-signal/mini-mouth/src/mic_signal.py')
parser.add_argument('--selftest', type=Path,
                    default=ROOT / 'candidate-mic-signal/mini-mouth/src/selftest.py')
options, remaining = parser.parse_known_args()
sys.argv[1:] = remaining


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signal = load(options.source, 'fixture_mic_signal')
selftest = load(options.selftest, 'fixture_selftest')
OPEN = {'alive': True, 'caps': True, 'mute': False}


class SubprocessCapture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='signal-child-fixture-')
        self.addCleanup(self.temp.cleanup)

    def argv(self, code):
        script = Path(self.temp.name) / 'emitter space \u05e9\u05dc\u05d5\u05dd.py'
        script.write_text('import sys,struct,time\n' + code + '\n', encoding='utf-8')
        return [sys.executable, '-u', str(script)]

    def classify(self, measured):
        return signal.observe(caps_read=lambda: OPEN,
                              occupancy=lambda: {'state': 'no_known_owner'},
                              argv=lambda: ['fixture-only'], capture=lambda argv: measured)

    async def test_zero_is_warn_with_real_sample_denominator(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(b'\\0\\0'*48000)"))
        result = self.classify(measured)
        self.assertEqual((result['status'], result['reason']), ('warn', 'near_zero_input'))
        self.assertEqual(result['metrics']['sample_count'], 48000)
        self.assertEqual(result['metrics']['max_abs'], 0)
        self.assertEqual(result['metrics']['nonzero_proportion'], 0)

    async def test_symmetric_dither_is_warn_without_hardware_verdict(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(struct.pack('<3h',-1,0,1)*16000)"))
        result = self.classify(measured)
        self.assertEqual(result['status'], 'warn')
        self.assertEqual(result['metrics']['max_abs'], 1)
        self.assertEqual(result['metrics']['nonzero_count'], 32000)
        self.assertEqual(result['metrics']['abs_gt1_count'], 0)
        self.assertIn('does not identify a hardware fault', result['guidance'])

    async def test_signal_above_one_unit_is_observation_not_speech_proof(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(struct.pack('<3h',-1000,0,1000)*16000)"))
        result = self.classify(measured)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['metrics']['max_abs'], 1000)
        self.assertEqual(result['metrics']['abs_gt1_count'], 32000)
        self.assertIn('does not prove speech', result['detail'])

    async def test_short_or_odd_stream_is_not_zero_input_verdict(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(b'\\0')"))
        result = self.classify(measured)
        self.assertEqual((result['status'], result['reason']), ('fail', 'incomplete'))
        self.assertEqual(result['metrics']['sample_count'], 0)
        self.assertIsNone(result['metrics']['max_abs'])
        self.assertEqual(result['metrics']['partial_bytes'], 1)

    async def test_capture_open_error_is_distinct_even_with_some_pcm(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(b'\\0\\0'*48000)\n"
                                                 "sys.stderr.write('FIXTURE endpoint busy')\nraise SystemExit(7)"))
        result = self.classify(measured)
        self.assertEqual(result['reason'], 'open_or_capture_error')
        self.assertEqual(result['exit_code'], 7)
        self.assertIn('FIXTURE endpoint busy', result['stderr_tail'])

    async def test_missing_binary_is_open_error_without_invented_zero_samples(self):
        measured = await signal.collect([str(Path(self.temp.name) / 'absent-program')])
        result = self.classify(measured)
        self.assertEqual(result['reason'], 'open_or_capture_error')
        self.assertIsNone(result['metrics']['max_abs'])

    async def test_stall_is_bounded_and_owned_child_is_reaped(self):
        measured = await signal.collect(self.argv('time.sleep(30)'), timeout_s=.5, cleanup_s=1)
        result = self.classify(measured)
        self.assertEqual(result['reason'], 'timeout')
        self.assertTrue(result['cleanup_ok'])
        self.assertIsNotNone(result['exit_code'])
        self.assertIsNone(result['metrics']['max_abs'])

    async def test_stderr_flood_is_drained_and_memory_retention_bounded(self):
        measured = await signal.collect(self.argv("sys.stderr.buffer.write(b'F'*3000000)\n"
                                                 "sys.stderr.flush()\nsys.stdout.buffer.write(b'\\0\\0'*48000)"))
        self.assertEqual(measured['outcome'], 'complete')
        self.assertEqual(len(measured['stderr_tail']), 1024)
        self.assertEqual(measured['metrics']['sample_count'], 48000)

    async def test_excess_pcm_is_bounded_and_not_a_complete_capture_claim(self):
        measured = await signal.collect(self.argv("sys.stdout.buffer.write(b'\\0\\0'*96000)"))
        self.assertEqual(measured['outcome'], 'excess_data')
        self.assertEqual(measured['bytes_received'], 192000)
        self.assertEqual(measured['metrics']['sample_count'], 48000)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'optional real FFmpeg lavfi fixture is unavailable')
    async def test_real_ffmpeg_synthetic_output_has_exact_two_second_sample_count(self):
        argv = [shutil.which('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                '-ac', '1', '-ar', '24000', '-f', 's16le', '-t', '2', '-']
        measured = await signal.collect(argv)
        self.assertEqual(measured['outcome'], 'complete', measured)
        self.assertEqual(measured['metrics']['sample_count'], 48000)

    async def test_real_caller_cancellation_reaps_only_the_owned_child(self):
        original = asyncio.create_subprocess_exec
        children = []

        async def record(*args, **kwargs):
            proc = await original(*args, **kwargs)
            children.append(proc)
            return proc

        with patch.object(asyncio, 'create_subprocess_exec', side_effect=record):
            task = asyncio.create_task(signal.collect(self.argv('time.sleep(30)')))
            for _ in range(600):
                if children:
                    break
                await asyncio.sleep(.005)
            self.assertEqual(len(children), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(children[0].returncode)

    async def test_mid_capture_caps_close_stops_and_reaps_owned_child(self):
        readings = 0

        async def gate():
            nonlocal readings
            readings += 1
            return OPEN if readings == 1 else {'alive': True, 'caps': False, 'mute': True}

        measured = await signal.collect(self.argv("time.sleep(30)\nsys.stdout.buffer.write(b'\\0\\0'*48000)"),
                                        caps_read_async=gate)
        result = self.classify(measured)
        self.assertEqual((result['status'], result['reason']), ('skip', 'caps_closed'))
        self.assertEqual(result['metrics']['sample_count'], 0)
        self.assertIsNotNone(result['exit_code'])
        self.assertTrue(result['cleanup_ok'])
        self.assertGreaterEqual(readings, 2)

    async def test_mid_capture_sensor_exception_stops_capture(self):
        readings = 0

        async def gate():
            nonlocal readings
            readings += 1
            if readings > 1:
                raise OSError('fixture sensor failure')
            return OPEN

        measured = await signal.collect(self.argv('time.sleep(30)'), caps_read_async=gate)
        self.assertEqual(measured['outcome'], 'caps_closed')
        self.assertIsNotNone(measured['exit_code'])
        self.assertTrue(measured['cleanup_ok'])

    async def test_denied_async_gate_never_spawns_a_child(self):
        async def gate():
            return {'alive': True, 'caps': False, 'mute': True}

        with patch.object(asyncio, 'create_subprocess_exec', side_effect=AssertionError('capture opened')):
            measured = await signal.collect(['fixture'], caps_read_async=gate)
        self.assertEqual(measured['outcome'], 'caps_closed')
        self.assertIsNone(measured['exit_code'])

    async def test_completed_capture_cancels_gate_monitor_cleanly(self):
        async def gate():
            return OPEN

        measured = await signal.collect(self.argv("sys.stdout.buffer.write(b'\\0\\0'*48000)"), caps_read_async=gate)
        self.assertEqual(measured['outcome'], 'complete')
        self.assertEqual(measured['metrics']['sample_count'], 48000)


class OptInGuards(unittest.TestCase):
    def test_caps_off_or_unknown_never_enumerates_or_captures(self):
        for gate in ({'alive': True, 'caps': False, 'mute': True},
                     {'alive': False, 'caps': True, 'mute': False}, None):
            with self.subTest(gate=gate):
                result = signal.observe(caps_read=lambda: gate,
                                        occupancy=lambda: self.fail('enumerated after denied Caps'),
                                        argv=lambda: self.fail('built argv after denied Caps'),
                                        capture=lambda argv: self.fail('opened capture after denied Caps'))
                self.assertEqual(result['reason'], 'caps_closed')

    def test_caps_change_before_open_is_checked_again(self):
        gates = iter([OPEN, {'alive': True, 'caps': False, 'mute': True}])
        result = signal.observe(caps_read=lambda: next(gates),
                                occupancy=lambda: {'state': 'no_known_owner'}, argv=lambda: ['fixture'],
                                capture=lambda argv: self.fail('opened after Caps changed'))
        self.assertEqual(result['reason'], 'caps_closed')

    def test_known_busy_and_unknown_enumeration_are_distinct_and_never_open(self):
        for state in ('busy', 'unknown'):
            result = signal.observe(caps_read=lambda: OPEN, occupancy=lambda: {'state': state},
                                    argv=lambda: self.fail('built argv while busy/unknown'),
                                    capture=lambda argv: self.fail('opened while busy/unknown'))
            self.assertEqual(result['reason'], 'capture_' + state)

    def test_owner_appearing_during_device_enumeration_prevents_open(self):
        states = iter([{'state': 'no_known_owner'}, {'state': 'busy', 'pids': [123]}])
        result = signal.observe(caps_read=lambda: OPEN, occupancy=lambda: next(states),
                                argv=lambda: ['fixture'], capture=lambda argv: self.fail('opened busy capture'))
        self.assertEqual(result['reason'], 'capture_busy')

    def test_process_identity_does_not_treat_unrelated_or_unknown_pid_as_busy(self):
        self.assertTrue(signal._driver_command(r'"C:\Program Files\Python\python.exe" "C:\bundle\mini-mouth\live.py"'))
        self.assertFalse(signal._driver_command(r'"C:\Python\python.exe" -c "print(\"live.py\")"'))
        platform = types.SimpleNamespace(process_rows=lambda timeout: [(os.getpid(), 0, 'python fixture.py'), (123, 0, '')],
                                         is_capture_command=lambda command: False)
        with patch.dict(sys.modules, mm_platform=platform):
            self.assertEqual(signal.capture_occupancy()['state'], 'no_known_owner')
            platform.process_rows = lambda timeout: [(123, 0, '')]
            self.assertEqual(signal.capture_occupancy()['state'], 'unknown')

    def test_same_diagnostic_ffmpeg_is_busy_without_broadening_cleanup_matcher(self):
        command = ('"C:\\Program Files\\FFmpeg\\ffmpeg.exe" -nostdin -hide_banner -loglevel error '
                   '-f dshow -i audio="Fixture Mic" -ac 1 -ar 24000 -f s16le -t 2 -')
        self.assertTrue(signal._diagnostic_capture_command(command))
        self.assertFalse(signal._diagnostic_capture_command('python -c "' + command + '"'))
        self.assertFalse(signal._diagnostic_capture_command(command.replace('-f dshow', '-f lavfi')))
        platform = types.SimpleNamespace(
            process_rows=lambda timeout: [(os.getpid(), 0, 'python fixture.py'), (123, 0, command)],
            is_capture_command=lambda command: False)
        with patch.dict(sys.modules, mm_platform=platform):
            result = signal.capture_occupancy()
        self.assertEqual(result['state'], 'busy')
        self.assertEqual(result['pids'], [123])

    def test_explicit_flag_dispatches_only_diagnostic_and_json(self):
        calls = []
        fake = types.SimpleNamespace(main=lambda **kwargs: calls.append(kwargs) or 0)
        probe = types.SimpleNamespace(caps_read=lambda: OPEN)
        with patch.dict(sys.modules, mic_signal=fake), patch.object(selftest, 'run', side_effect=AssertionError('full selftest')):
            self.assertEqual(selftest.main(['--mic-signal', '--json'], probe), 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]['as_json'])
        self.assertIs(calls[0]['caps_read'], probe.caps_read)

    def test_default_dispatch_passes_the_live_async_sensor_adapter(self):
        calls = []
        fake = types.SimpleNamespace(main=lambda **kwargs: calls.append(kwargs) or 0)
        with patch.dict(sys.modules, mic_signal=fake):
            self.assertEqual(selftest.main(['--mic-signal', '--json']), 0)
        self.assertIs(calls[0]['caps_read_async'], selftest._default_caps_read_async)
        self.assertIs(calls[0]['caps_read'], selftest._default_caps_read)

    def test_no_device_conflict_cannot_open_and_normal_selftest_does_not_dispatch(self):
        fake = types.SimpleNamespace(main=lambda **kwargs: self.fail('unexpected mic-signal capture'))
        with patch.dict(sys.modules, mic_signal=fake), contextlib.redirect_stderr(io.StringIO()), \
             contextlib.redirect_stdout(io.StringIO()), patch.object(selftest, 'run', return_value=[]):
            self.assertEqual(selftest.main(['--mic-signal', '--no-device']), 2)
            self.assertEqual(selftest.main(['--no-device']), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
