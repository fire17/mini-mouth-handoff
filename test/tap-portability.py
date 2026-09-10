"""Real temporary sidecar/link fixtures; no live-wall, graph, credentials or audio."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'candidate-tap-portability/mini-mouth/src/tap_log.py')
options, rest = parser.parse_known_args()
SOURCE = options.source


class TapPortability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tap portability שלום ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.module = types.ModuleType('isolated_tap_log')
        wall = types.SimpleNamespace(surface=lambda _: str(self.directory / 'default sidecar'))
        with patch.dict(sys.modules, {'live_wall': wall}):
            exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), self.module.__dict__)
        self.root = self.directory / 'sidecar'
        self.links = self.directory / 'discovery'
        self.log = self.module.TapLog(root=str(self.root), link_dir=str(self.links))
        self.addCleanup(self.log.close)

    def rows(self):
        return [json.loads(line) for line in Path(self.log.path).read_text(encoding='utf-8').splitlines()]

    def privilege_error(self):
        error = OSError(22, 'fixture required privilege is not held')
        error.winerror = 1314
        return error

    def test_symlink_privilege_denial_falls_back_to_actual_hardlink(self):
        with patch.object(os, 'symlink', side_effect=self.privilege_error()):
            self.assertTrue(self.log.open({'driver': 'fixture'}))
        self.assertFalse(os.path.islink(self.log.link))
        self.assertTrue(os.path.samefile(self.log.path, self.log.link))
        self.log.speech_started()
        self.log.you_delta('שלום ')
        self.log.you_delta('🐙')
        self.log.you('שלום 🐙')
        self.log.speech_stopped()
        self.assertEqual(Path(self.log.link).read_bytes(), Path(self.log.path).read_bytes())
        rows = self.rows()
        self.assertEqual(rows[0]['ev'], 'run')
        self.assertEqual([r['text'] for r in rows if r.get('ev') == 'you_delta'], ['שלום ', '🐙'])
        self.assertFalse(any('ev' in r and 'ws' in r for r in rows))
        self.log.close()
        self.assertFalse(os.path.lexists(self.log.link))
        self.assertEqual(self.rows()[-1]['ev'], 'run_end')

    def test_discovery_failure_keeps_framed_sidecar_and_does_not_hide_write_failure(self):
        output = io.StringIO()
        with patch.object(os, 'symlink', side_effect=self.privilege_error()), patch.object(os, 'link', side_effect=OSError(18, 'cross-volume fixture')), contextlib.redirect_stdout(output):
            self.assertTrue(self.log.open())
            self.log.you('durable proof')
        self.assertEqual(self.rows()[0]['ev'], 'run')
        self.assertEqual(self.rows()[-1]['text'], 'durable proof')
        self.assertIn('sidecar remains active', output.getvalue())
        self.assertNotIn('CANNOT OPEN', output.getvalue())
        self.assertFalse(self.log.broken)
        self.assertTrue(self.log.discovery_error)
        self.log.handle.close()
        with contextlib.redirect_stdout(output):
            self.log.event('after-closed-handle')
        self.assertIn('WRITE FAILED', output.getvalue(), 'discovery errors cannot suppress a real sidecar write error')

    @unittest.skipIf(os.name == 'nt', 'macOS/Linux symlink contract; Windows fallback tested separately')
    def test_existing_posix_discovery_remains_a_symlink_and_is_removed_at_close(self):
        self.assertTrue(self.log.open())
        self.assertTrue(os.path.islink(self.log.link))
        self.assertTrue(os.path.samefile(self.log.path, self.log.link))
        self.log.close()
        self.assertFalse(os.path.lexists(self.log.link))
        self.assertTrue(Path(self.log.path).exists())

    def test_close_does_not_remove_a_replacement_discovery_file(self):
        with patch.object(os, 'symlink', side_effect=self.privilege_error()):
            self.assertTrue(self.log.open())
        os.unlink(self.log.link)
        Path(self.log.link).write_text('different publisher', encoding='utf-8')
        self.log.close()
        self.assertEqual(Path(self.log.link).read_text(encoding='utf-8'), 'different publisher')
        self.assertEqual(self.rows()[-1]['ev'], 'run_end')

    def test_direct_discovery_path_is_never_unlinked_as_a_link(self):
        self.log = self.module.TapLog(root=str(self.root), link_dir=str(self.root))
        self.addCleanup(self.log.close)
        self.assertTrue(self.log.open())
        self.log.you('same-directory proof')
        self.log.close()
        self.assertEqual(self.rows()[0]['ev'], 'run')
        self.assertEqual(self.rows()[-1]['ev'], 'run_end')

    def test_genuine_sidecar_open_failure_is_reported_and_nonfatal(self):
        self.root.write_text('file prevents directory creation', encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(self.log.open())
            self.log.you('must not write')
        self.assertIsNone(self.log.handle)
        self.assertIn('CANNOT OPEN', output.getvalue())
        self.assertEqual(self.root.read_text(encoding='utf-8'), 'file prevents directory creation')

    @unittest.skipUnless(os.name == 'nt', 'requires actual Windows temp-directory selection')
    def test_windows_discovery_uses_user_temporary_directory(self):
        self.assertEqual(self.module.LINK_DIR, tempfile.gettempdir())


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *rest], verbosity=2)
