"""Synthetic subprocess -> actual r5 Mic -> actual driver pump, with no devices.

All child processes are this Python interpreter emitting fixed fixture bytes.
Only the requested classes/methods are AST-extracted; no live driver is imported.
"""
import argparse
import array
import ast
import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--archive', type=Path,
                    default=ROOT.parent / 'windows-handoff/mini-mouth-windows-candidate-2026-09-11-r5.zip')
parser.add_argument('--candidate', type=Path)
options, remaining = parser.parse_known_args()
sys.argv[1:] = remaining
ARCHIVE = options.archive
CANDIDATE = options.candidate.read_text(encoding='utf-8') if options.candidate else None
assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == '43335262bbfe5ebacd6f722112ed6e584ad3bab282315621b731303d0f825281'
with zipfile.ZipFile(ARCHIVE) as z:
    AUDIO = z.read('mini-mouth/src/audio_io.py').decode('utf-8')
    DRIVER = z.read('mini-mouth/src/rt_driver.py').decode('utf-8')
    PLATFORM = z.read('mini-mouth/src/mm_platform.py').decode('utf-8')


def mic_class(argv, audio_source=AUDIO):
    node = next(n for n in ast.parse(audio_source).body if isinstance(n, ast.ClassDef) and n.name == 'Mic')
    namespace = dict(asyncio=asyncio, BYTES_PER_MS=48, mic_argv=lambda: argv)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'r5/audio_io.py', 'exec'), namespace)
    return namespace['Mic']


class RealPipe(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mic-pipe-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.mics = []

    async def asyncTearDown(self):
        for mic in self.mics:
            if mic.proc is not None:
                mic.kill()
                await asyncio.wait_for(mic.proc.wait(), 2)
                state = getattr(mic, '_capture', None)
                if state is not None:
                    await asyncio.wait_for(state['exit_task'], 2)

    def emitter(self, payload, *, stderr=b'', code=0, odd_boundary=False):
        script = Path(self.temp.name) / 'emit fixture \u05e9\u05dc\u05d5\u05dd.py'
        script.write_text(
            'import sys,time\nfrom pathlib import Path\n'
            'payload=' + repr(payload) + '\n'
            'sys.stderr.buffer.write(' + repr(stderr) + ');sys.stderr.buffer.flush()\n' +
            ('sys.stdout.buffer.write(payload[:1]);sys.stdout.buffer.flush()\n'
             'ack=Path(sys.argv[1])\n'
             'ack.with_suffix(".ready").touch()\n'
             'for _ in range(1000):\n'
             ' if ack.exists(): break\n'
             ' time.sleep(.005)\n'
             'else: raise SystemExit(99)\n'
             'sys.stdout.buffer.write(payload[1:]);sys.stdout.buffer.flush()\n'
             if odd_boundary else
             'sys.stdout.buffer.write(payload);sys.stdout.buffer.flush()\n') +
            'raise SystemExit(' + repr(code) + ')\n', encoding='utf-8')
        ack = Path(self.temp.name) / 'fixture-ack'
        return [sys.executable, '-u', str(script), str(ack)], ack

    async def test_mic_reads_only_stdout_and_preserves_pcm_bytes(self):
        pcm = struct.pack('<9h', 0, 1, -1, 256, -256, 16384, -16384, 32767, -32768) * 1000
        argv, _ = self.emitter(pcm, stderr=b'FIXTURE diagnostic; this is not PCM\n' * 20000)
        mic = mic_class(argv)()
        self.mics.append(mic)
        await mic.start()
        chunks = []
        while chunk := await asyncio.wait_for(mic.read(), 3):
            self.assertLessEqual(len(chunk), 4800)
            chunks.append(chunk)
        self.assertEqual(b''.join(chunks), pcm)
        self.assertEqual(await mic.proc.wait(), 0)
        self.assertIsNone(mic.proc.stderr, 'r5 discards stderr; it never becomes audio bytes')

    async def test_r5_hides_native_capture_exit_and_stderr(self):
        argv, _ = self.emitter(b'', stderr=b'FIXTURE failed to open capture device\n', code=7)
        mic = mic_class(argv)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            await mic.start()
            self.assertEqual(await asyncio.wait_for(mic.read(), 3), b'')
            self.assertEqual(await mic.proc.wait(), 7)
        self.assertEqual(output.getvalue(), '')

    async def test_odd_read_boundaries_preserve_bytes_but_expose_per_chunk_meter_alignment(self):
        pcm = struct.pack('<h', 256) * 8
        argv, ack = self.emitter(pcm, odd_boundary=True)
        mic = mic_class(argv)()
        self.mics.append(mic)
        await mic.start()
        first = await asyncio.wait_for(mic.read(), 3)
        self.assertEqual(first, pcm[:1])
        ack.touch()
        rest = b''
        while chunk := await asyncio.wait_for(mic.read(), 3):
            rest += chunk
        self.assertEqual(first + rest, pcm)
        # This is the exact decoding expression used by mic_pump, applied to
        # an intentionally odd boundary. It is not a claim FFmpeg does this on
        # either real PC; RUN7's direct dshow result precedes this Python code.
        values = array.array('h')
        values.frombytes(rest[:len(rest) // 2 * 2])
        self.assertEqual(sys.byteorder, 'little')
        self.assertEqual(max(map(abs, values)), 1)
        self.assertEqual(max(abs(x[0]) for x in struct.iter_unpack('<h', pcm)), 256)

    async def pump_case(self, peak, muted, playing, audio_source=AUDIO):
        pcm = struct.pack('<2h', peak, -peak) * 100
        argv, _ = self.emitter(pcm)
        Mic = mic_class(argv, audio_source)
        observed = dict(levels=[], sent=[], archived=bytearray(), dropped=0)
        done = asyncio.Event()

        async def noop(*args, **kwargs):
            pass

        async def send(row):
            observed['sent'].append(row)
            done.set()

        def feed(chunk):
            observed['archived'].extend(chunk)
            if playing:
                done.set()

        def drop(size):
            observed['dropped'] += size
            done.set()

        namespace = dict(asyncio=asyncio, array=array, base64=base64, time=time,
                         BARGE=False, now_ms=lambda: int(time.time()*1000), json=json)
        body = next(n.body for n in ast.parse(DRIVER).body if isinstance(n, ast.ClassDef) and n.name == 'Driver')
        nodes = [n for n in body if getattr(n, 'name', None) in {'mic_pump', '_put_mic_level'}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'r5/rt_driver.py', 'exec'), namespace)
        node = types.SimpleNamespace
        driver = node(player=node(active=playing), muted=muted, _mic_peak_window=0,
                      _paused=None, _onset_pending=False, _narrating=False,
                      LEAK_BAR=4000, echo_buf=bytearray(), _his_over_mind_ms=0,
                      archive=node(feed=feed, drop=drop), meter=node(feed=lambda *a, **k: None),
                      rt=node(status=node(), spec=node(half_duplex=node(value=True)),
                              turn=node(state=node(value='idle'))),
                      mic_health=node(chunk=lambda: None), warm_speaker=noop,
                      mic_watchdog=noop, player_watchdog=noop, send=send,
                      his_voice_over_mind=lambda value: False, finish_echo_capture=lambda: None,
                      report_error=lambda *a: (_ for _ in ()).throw(AssertionError(a)),
                      put=lambda obj, key, value: observed['levels'].append((key, value)))
        driver._put_mic_level = types.MethodType(namespace['_put_mic_level'], driver)
        with patch.dict(sys.modules, audio_io=node(Mic=Mic, PipeAMic=None),
                        swap_bridge=node(stop_live=lambda: 0)), contextlib.redirect_stdout(io.StringIO()):
            task = asyncio.create_task(namespace['mic_pump'](driver))
            try:
                await asyncio.wait_for(done.wait(), 3)
                await asyncio.sleep(.03)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                if getattr(driver, 'mic', None) is not None:
                    self.mics.append(driver.mic)
        levels = [v for k, v in observed['levels'] if k == 'mic_level']
        self.assertEqual(levels, [] if muted else [peak])
        self.assertEqual(driver._mic_peak_window, peak if playing else 0)
        if muted or playing:
            self.assertEqual(observed['sent'], [])
        else:
            self.assertEqual(b''.join(base64.b64decode(r['audio']) for r in observed['sent']), pcm)
        self.assertEqual(bytes(observed['archived']), b'' if muted else pcm)
        self.assertEqual(observed['dropped'], len(pcm) if muted else 0)

    async def test_real_pipe_peak_one_is_not_rescaled(self):
        await self.pump_case(1, False, False)

    async def test_real_pipe_half_scale_reaches_meter_and_server_unchanged(self):
        await self.pump_case(16384, False, False)

    async def test_real_pipe_heard_peak_precedes_mute_and_muted_audio_is_not_sent(self):
        await self.pump_case(16384, True, True)

    async def test_real_pipe_meter_precedes_half_duplex_and_playing_audio_is_not_sent(self):
        await self.pump_case(16384, False, True)


class WindowsArgv(unittest.TestCase):
    def test_conversion_flags_belong_to_output_and_pipe_is_stdout(self):
        names = {'capture_input_args', 'mic_argv'}
        nodes = [n for n in ast.parse(PLATFORM).body if getattr(n, 'name', None) in names]
        namespace = dict(is_win=lambda: True, which=lambda name: name, RATE=24000,
                         default_mic=lambda: 'FIXTURE device with spaces')
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'r5/mm_platform.py', 'exec'), namespace)
        argv = namespace['mic_argv']()
        source = argv.index('-i')
        self.assertEqual(argv[source+1], 'audio=FIXTURE device with spaces')
        self.assertGreater(argv.index('-ac'), source)
        self.assertGreater(argv.index('-ar'), source)
        self.assertEqual(argv[-3:], ['-f', 's16le', '-'])


@unittest.skipUnless(CANDIDATE is not None, 'pass --candidate to test the isolated fix')
class CandidatePipe(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RealPipe.asyncSetUp
    asyncTearDown = RealPipe.asyncTearDown
    emitter = RealPipe.emitter

    async def wait_ready(self, ack):
        async def wait():
            while not ack.with_suffix('.ready').exists():
                await asyncio.sleep(.005)
        await asyncio.wait_for(wait(), 3)

    async def read_all(self, mic):
        chunks = []
        while chunk := await asyncio.wait_for(mic.read(), 3):
            self.assertEqual(len(chunk) % 2, 0, 'forward only complete s16le samples')
            self.assertLessEqual(len(chunk), 4800)
            chunks.append(chunk)
        state = getattr(mic, '_capture', None)
        if state is not None:
            await asyncio.wait_for(state['exit_task'], 3)
        return b''.join(chunks)

    async def test_odd_boundary_is_carried_without_false_eof_or_sample_shift(self):
        pcm = struct.pack('<h', 256) * 8
        argv, ack = self.emitter(pcm, odd_boundary=True)
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            pending = asyncio.create_task(mic.read())
            try:
                await self.wait_ready(ack)
                await asyncio.sleep(.01)
                self.assertFalse(pending.done(), 'one byte cannot be returned as a PCM frame')
                ack.touch()
                first = await asyncio.wait_for(pending, 3)
                rest = await self.read_all(mic)
            finally:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
        self.assertEqual(first + rest, pcm)
        self.assertEqual(max(abs(x[0]) for x in struct.iter_unpack('<h', first + rest)), 256)

    async def test_final_orphan_byte_is_reported_once_and_never_forwarded(self):
        pcm = struct.pack('<2h', 256, -256)
        argv, _ = self.emitter(pcm + b'\x7f')
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            self.assertEqual(await self.read_all(mic), pcm)
            self.assertEqual(await mic.read(), b'')
        self.assertEqual(output.getvalue().count('incomplete PCM byte'), 1)

    async def test_capture_failure_before_pcm_reports_exit_and_bounded_stderr(self):
        argv, _ = self.emitter(b'', stderr=b'FIXTURE cannot open capture device\n', code=7)
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            self.assertEqual(await self.read_all(mic), b'')
        self.assertIn('capture exited (code=7', output.getvalue())
        self.assertIn('FIXTURE cannot open capture device', output.getvalue())
        self.assertEqual(output.getvalue().count('capture exited'), 1)

    async def test_stderr_flood_does_not_block_pcm_and_is_retained_and_logged_boundedly(self):
        pcm = struct.pack('<3h', -32768, 1, 32767) * 4000
        stderr = b'FIXTURE\x1b[31m\n' * 200000
        argv, _ = self.emitter(pcm, stderr=stderr)
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            self.assertEqual(await self.read_all(mic), pcm)
        self.assertLessEqual(len(mic._capture['stderr']), 4096)
        self.assertLess(len(output.getvalue()), 2300)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertNotIn('\x1b', output.getvalue())

    async def test_requested_kill_does_not_claim_unexpected_capture_failure(self):
        argv = [sys.executable, '-u', '-c', 'import time;time.sleep(30)']
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            mic.kill()
            await asyncio.wait_for(mic._capture['exit_task'], 3)
        self.assertEqual(output.getvalue(), '')

    async def test_restart_cannot_mix_old_carry_or_diagnostics_into_new_child(self):
        argv, ack = self.emitter(b'\x7f\x12', odd_boundary=True)
        mic = mic_class(argv, CANDIDATE)()
        self.mics.append(mic)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await mic.start()
            old = mic._capture
            pending = asyncio.create_task(mic.read())
            try:
                await self.wait_ready(ack)
                await asyncio.sleep(.01)
                self.assertFalse(pending.done())
                mic.kill()
                expected = struct.pack('<2h', 512, -512)
                new_argv, _ = self.emitter(expected)
                argv[:] = new_argv
                await mic.start()
                first = await asyncio.wait_for(pending, 3)
                self.assertEqual(first + await self.read_all(mic), expected)
                await asyncio.wait_for(old['exit_task'], 3)
            finally:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
        self.assertTrue(old['stopped'])
        self.assertEqual(output.getvalue().count('capture exited'), 1)

    async def test_candidate_pipe_and_actual_driver_preserve_meter_bytes_and_consent_gates(self):
        for peak, muted, playing in [(1, False, False), (16384, False, False),
                                      (16384, True, True), (16384, False, True)]:
            await RealPipe.pump_case(self, peak, muted, playing, audio_source=CANDIDATE)


if __name__ == '__main__':
    if options.candidate:
        print('Candidate audio_io SHA256=' + hashlib.sha256(options.candidate.read_bytes()).hexdigest(), flush=True)
    unittest.main(verbosity=2)
