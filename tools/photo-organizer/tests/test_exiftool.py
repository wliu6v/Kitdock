"""Integration tests with genuine ExifTool parsing; set PHOTO_EXIFTOOL to enable."""

import struct
import zlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from photo_organizer.core import Options, organize
from photo_organizer.metadata import ExifTool

EXIFTOOL = os.environ.get("PHOTO_EXIFTOOL") or shutil.which("exiftool")


@unittest.skipUnless(EXIFTOOL, "ExifTool integration dependency is not installed")
class ExifToolTests(unittest.TestCase):
    def test_real_png_timestamp_and_cli_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "中文 images"
            source.mkdir()
            image = source / "sample.png"
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                              + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))
            subprocess.run([EXIFTOOL, "-overwrite_original", "-EXIF:DateTimeOriginal=2026:10:01 12:30:40", str(image)], check=True, capture_output=True)
            meta = ExifTool(EXIFTOOL).read(image)
            self.assertEqual(meta.captured.strftime("%Y%m%d_%H%M%S"), "20261001_123040")
            options = Options((source,), root / "out", exiftool=EXIFTOOL)
            result = organize(options)
            self.assertEqual((result.copied, result.errors), (1, 0))
            self.assertEqual((root / "out/20261001_123040.png").read_bytes(), image.read_bytes())
            self.assertEqual(organize(options).skipped, 1)
