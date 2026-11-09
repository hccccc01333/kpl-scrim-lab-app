import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import media_tools  # noqa: E402


class MediaToolsTests(unittest.TestCase):
    """ffmpeg 解析：应用内副本优先，其次 PATH，都没有就退回裸命令名。"""

    def test_prefers_local_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            (bin_dir / 'ffmpeg.exe').write_bytes(b'')
            (bin_dir / 'ffprobe.exe').write_bytes(b'')
            with (
                mock.patch.object(media_tools, '_SEARCH_PATHS', (bin_dir,)),
                mock.patch.object(media_tools.shutil, 'which', return_value='C:/x/ffmpeg.exe'),
            ):
                self.assertEqual(media_tools.ffmpeg(), str(bin_dir / 'ffmpeg.exe'))
                self.assertEqual(media_tools.source(), 'bundled')

    def test_falls_back_to_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(media_tools, '_SEARCH_PATHS', (Path(tmp),)),
                mock.patch.object(media_tools.shutil, 'which',
                                  side_effect=lambda name: f'C:/path/{name}.exe'),
            ):
                self.assertEqual(media_tools.ffmpeg(), 'C:/path/ffmpeg.exe')
                self.assertEqual(media_tools.source(), 'path')

    def test_missing_returns_bare_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(media_tools, '_SEARCH_PATHS', (Path(tmp),)),
                mock.patch.object(media_tools.shutil, 'which', return_value=None),
            ):
                self.assertEqual(media_tools.ffmpeg(), 'ffmpeg')
                self.assertFalse(media_tools.available())
                self.assertEqual(media_tools.source(), 'missing')


if __name__ == '__main__':
    unittest.main()
