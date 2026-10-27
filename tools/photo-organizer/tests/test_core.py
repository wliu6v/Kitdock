import errno
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from photo_organizer.core import Options, copy_verified, organize, sha256
from photo_organizer.metadata import Metadata, from_tags, offset_zone


class Reader:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def read(self, path):
        value = self.mapping.get(path.name, Metadata(datetime(2026, 10, 1, 12, 30, 40), "test"))
        if isinstance(value, Exception):
            raise value
        return value


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "iPhone 中文"
        self.b = self.root / "Android"
        self.out = self.root / "整理"
        self.a.mkdir()
        self.b.mkdir()

    def file(self, directory, name, data=b"image"):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_job(self, **kwargs):
        options = kwargs.pop("options", Options((self.a, self.b), self.out))
        return organize(options, reader=kwargs.pop("reader", Reader()), **kwargs)

    def test_merge_companions_and_collision_and_rerun(self):
        for ext in ("HEIC", "MOV", "AAE"):
            self.file(self.a, "IMG_1." + ext, ext.encode())
        self.file(self.b, "other.jpg", b"other")
        result = self.run_job()
        self.assertEqual((result.copied, result.errors), (4, 0))
        names = {p.name for p in self.out.iterdir() if not p.name.startswith(".")}
        companions = {Path(name).stem for name in names if Path(name).suffix != ".jpg"}
        self.assertEqual(len(companions), 1)
        self.assertNotIn(next(name for name in names if name.endswith(".jpg")).removesuffix(".jpg"), companions)
        self.assertEqual(self.run_job().skipped, 4)
        self.assertEqual(len(list(self.a.iterdir())), 3)

    def test_dry_run_writes_nothing(self):
        self.file(self.a, "x.jpg")
        result = self.run_job(options=Options((self.a,), self.out, dry_run=True))
        self.assertEqual(result.planned, 1)
        self.assertFalse(self.out.exists())

    def test_preview_dedup_matches_real_run(self):
        self.file(self.a, "one.jpg")
        self.file(self.b, "two.jpg")
        preview = self.run_job(options=Options((self.a, self.b), self.out, dry_run=True))
        real = self.run_job()
        self.assertEqual((preview.planned, preview.skipped), (real.copied, real.skipped))
        self.assertEqual([r["destination"] for r in preview.records], [r["destination"] for r in real.records])

    def test_missing_time_and_filename_fallback(self):
        self.file(self.a, "unknown.png")
        self.file(self.b, "IMG_20261002_090807.jpg")
        reader = Reader({"unknown.png": Metadata(), "IMG_20261002_090807.jpg": Metadata()})
        result = self.run_job(reader=reader)
        self.assertTrue(any("时间待确认" in row["destination"] for row in result.records))
        self.assertTrue((self.out / "20261002_090807.jpg").exists())
        result = self.run_job(options=Options((self.a,), self.root / "skip", missing_time="skip"), reader=reader)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.records[0]["status"], "skipped")

    def test_metadata_error_keeps_entire_group(self):
        self.file(self.a, "x.heic")
        self.file(self.a, "x.mov")
        self.file(self.b, "ok.png")
        result = self.run_job(reader=Reader({"x.mov": ValueError("bad metadata")}))
        self.assertEqual((result.errors, result.copied), (2, 1))

    def test_cancel_then_recover_partial_group(self):
        self.file(self.a, "x.jpg")
        self.file(self.a, "x.mov", b"video")
        cancel = threading.Event()
        def progress(event):
            if event.phase == "copy" and event.done == 1:
                cancel.set()
        first = self.run_job(cancel=cancel, progress=progress)
        self.assertTrue(first.cancelled)
        self.assertEqual(first.copied, 1)
        second = self.run_job()
        self.assertEqual((second.copied, second.skipped, second.errors), (1, 1, 0))
        self.assertTrue((self.out / "20261001_123040.mov").exists())
        self.assertFalse((self.out / ".photo-organizer.lock").exists())

    def test_modified_destination_never_overwritten(self):
        self.file(self.a, "x.jpg")
        self.run_job()
        original_target = self.out / "20261001_123040.jpg"
        original_target.write_bytes(b"edited externally")
        result = self.run_job()
        self.assertEqual(result.copied, 1)
        self.assertEqual(original_target.read_bytes(), b"edited externally")
        self.assertEqual((self.out / "20261001_123040_02.jpg").read_bytes(), b"image")

    def test_identical_sources_deduplicate(self):
        self.file(self.a, "x.jpg")
        self.file(self.b, "y.JPG")
        result = self.run_job()
        self.assertEqual((result.copied, result.skipped), (1, 1))

    def test_output_overlap_rejected(self):
        for output in (self.a, self.a / "out", self.root):
            with self.assertRaises(ValueError):
                self.run_job(options=Options((self.a,), output))

    def test_repeated_and_nested_sources_scanned_once(self):
        self.file(self.a, "sub/x.jpg")
        result = self.run_job(options=Options((self.a, self.a / "sub", self.a), self.out))
        self.assertEqual(result.total, 1)

    def test_duplicate_extensions_are_not_overwritten(self):
        # Run on case-sensitive filesystems only.
        one = self.file(self.a, "x.jpg", b"a")
        two = self.file(self.a, "x.JPG", b"b")
        if one.samefile(two):
            self.skipTest("Case-insensitive filesystem")
        result = self.run_job()
        self.assertEqual(result.errors, 2)

    def test_content_id_joins_renamed_live_photo(self):
        self.file(self.a, "image.heic")
        self.file(self.a, "video.mov", b"movie")
        meta = Metadata(datetime(2026, 10, 1, 12, 30, 40), "test", content_id="pair")
        result = self.run_job(reader=Reader({"image.heic": meta, "video.mov": meta}))
        self.assertEqual(len({Path(row["destination"]).stem for row in result.records}), 1)

    def test_location_failure_does_not_lose_photos(self):
        self.file(self.a, "x.jpg")
        meta = Metadata(datetime(2026, 10, 1), "test", coordinates=(29.55, 106.5))
        with patch("photo_organizer.core.Geocoder.lookup", side_effect=OSError("offline")):
            result = self.run_job(options=Options((self.a,), self.out, geocode_url="https://example.com/reverse"), reader=Reader({"x.jpg": meta}))
        self.assertEqual(result.copied, 1)
        self.assertIn("Location lookup failed", result.records[0]["warnings"][0])

    def test_atomic_copy_rejects_existing_target_and_source_change(self):
        source = self.file(self.a, "x.jpg")
        target = self.file(self.b, "target.jpg", b"keep")
        cancel = threading.Event()
        digest = sha256(source, cancel)
        with self.assertRaises(FileExistsError):
            copy_verified(source, target, digest, cancel)
        self.assertEqual(target.read_bytes(), b"keep")
        with self.assertRaises(ValueError):
            copy_verified(source, self.b / "new.jpg", "wrong-hash", cancel)
        self.assertFalse((self.b / "new.jpg").exists())
        self.assertFalse(list(self.b.glob(".photo-copy-*")))

    def test_exfat_fallback_preserves_bytes_and_existing_target(self):
        source = self.file(self.a, "x.jpg")
        target = self.b / "target.jpg"
        cancel = threading.Event()
        digest = sha256(source, cancel)
        with patch("photo_organizer.core.os.link", side_effect=OSError(errno.EOPNOTSUPP, "unsupported")):
            copy_verified(source, target, digest, cancel)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            with self.assertRaises(FileExistsError):
                copy_verified(source, target, digest, cancel)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_lock_prevents_concurrent_output(self):
        self.out.mkdir()
        (self.out / ".photo-organizer.lock").write_text("pid=123")
        with self.assertRaises(ValueError):
            self.run_job()
        self.assertTrue((self.out / ".photo-organizer.lock").exists())

    def test_report_is_valid_jsonl(self):
        self.file(self.a, "x.jpg")
        result = self.run_job()
        rows = [json.loads(line) for line in result.report.read_text().splitlines()]
        self.assertEqual(rows, result.records)


class MetadataTests(unittest.TestCase):
    def test_iphone_wall_clock_preserved(self):
        meta = from_tags({"QuickTime:CreationDate": "2026:10:01 12:30:40+09:00", "QuickTime:CreateDate": "2026:10:01 03:30:40"}, offset_zone("+08:00"))
        self.assertEqual(meta.captured.hour, 12)

    def test_utc_video_converted_deterministically(self):
        meta = from_tags({"QuickTime:CreateDate": "2026:10:01 23:30:40"}, offset_zone("+08:00"))
        self.assertEqual(meta.captured.isoformat(), "2026-10-02T07:30:40+08:00")

    def test_gps_hemisphere_and_safe_location(self):
        meta = from_tags({"EXIF:GPSLatitude": 30, "EXIF:GPSLongitude": 110,
                          "EXIF:GPSLatitudeRef": "S", "EXIF:GPSLongitudeRef": "W",
                          "XMP:City": "重庆市", "XMP:Location": "李子坝/<>"}, offset_zone("+08:00"))
        self.assertEqual(meta.coordinates, (-30, -110))
        self.assertEqual(meta.location, "重庆市李子坝")

    def test_invalid_dates_and_offsets(self):
        self.assertIsNone(from_tags({"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"}, offset_zone("+08:00")).captured)
        for value in ("8", "+25:00", "+08:99", "+14:01"):
            with self.assertRaises(ValueError):
                offset_zone(value)


if __name__ == "__main__":
    unittest.main()
