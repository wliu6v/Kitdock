"""Read metadata without decoding or modifying media."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

IMAGES = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".dng", ".tif", ".tiff", ".webp", ".avif"}
VIDEOS = {".mov", ".mp4", ".m4v", ".avi", ".3gp", ".3g2"}
SIDECARS = {".aae", ".xmp"}
SUPPORTED = IMAGES | VIDEOS | SIDECARS


@dataclass(frozen=True)
class Metadata:
    captured: datetime | None = None
    time_source: str = "missing"
    location: str = ""
    coordinates: tuple[float, float] | None = None
    content_id: str = ""
    warning: str = ""


def clean_label(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "", value)
    return value.strip(" .")[:60]


def parse_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", value.strip())
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def offset_zone(value: str) -> timezone:
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", value):
        raise ValueError("UTC offset must use +08:00 or -05:00 format")
    hours, minutes = map(int, value[1:].split(":"))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        raise ValueError("UTC offset must be within -14:00 to +14:00")
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if value[0] == "-" else 1)))


def from_tags(tags: dict, video_zone: timezone) -> Metadata:
    # String timestamps preserve the camera's wall clock, including explicit offsets.
    keys = (
        "Composite:SubSecDateTimeOriginal", "EXIF:DateTimeOriginal",
        "XMP:DateTimeOriginal", "QuickTime:CreationDate", "QuickTime:DateTimeOriginal",
        "EXIF:CreateDate", "XMP:CreateDate", "PNG:CreationTime",
        "QuickTime:CreateDate", "QuickTime:MediaCreateDate", "QuickTime:TrackCreateDate",
    )
    captured, source = None, "missing"
    for key in keys:
        parsed = parse_date(tags.get(key))
        if parsed is None:
            continue
        if key in {"QuickTime:CreateDate", "QuickTime:MediaCreateDate", "QuickTime:TrackCreateDate"}:
            parsed = parsed.replace(tzinfo=timezone.utc).astimezone(video_zone)
        captured, source = parsed, key
        break
    city = tags.get("XMP:City") or tags.get("IPTC:City") or ""
    place = tags.get("XMP:Location") or tags.get("IPTC:Sub-location") or ""
    location = clean_label(str(city) + (str(place) if place != city else ""))
    coordinates = None
    try:
        lat = float(tags.get("Composite:GPSLatitude", tags.get("EXIF:GPSLatitude")))
        lon = float(tags.get("Composite:GPSLongitude", tags.get("EXIF:GPSLongitude")))
        if tags.get("EXIF:GPSLatitudeRef") == "S":
            lat = -abs(lat)
        if tags.get("EXIF:GPSLongitudeRef") == "W":
            lon = -abs(lon)
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            coordinates = lat, lon
    except (TypeError, ValueError):
        pass
    identifier = tags.get("QuickTime:ContentIdentifier") or tags.get("MakerNotes:ContentIdentifier") or ""
    return Metadata(captured, source, location, coordinates, str(identifier), str(tags.get("ExifTool:Warning", "")))


class ExifTool:
    def __init__(self, executable: str = "exiftool", utc_offset: str = "+08:00"):
        self.executable = shutil.which(executable)
        if not self.executable:
            raise ValueError("ExifTool not found. Install it or specify --exiftool /path/to/exiftool.")
        self.zone = offset_zone(utc_offset)

    def read(self, path: Path) -> Metadata:
        if path.suffix.lower() in SIDECARS:
            return Metadata()
        # -G0 keeps tag namespaces stable across image containers. No write options.
        result = subprocess.run(
            [self.executable, "-json", "-G0", "-n", "-charset", "filename=UTF8",
             "-api", "QuickTimeUTC=0", "-DateTimeOriginal", "-SubSecDateTimeOriginal",
             "-CreationDate", "-CreateDate", "-MediaCreateDate", "-TrackCreateDate",
             "-CreationTime", "-City", "-Location", "-Sub-location", "-GPSLatitude",
             "-GPSLongitude", "-GPSLatitudeRef", "-GPSLongitudeRef", "-ContentIdentifier",
             "-Warning", "-Error", str(path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "ExifTool could not read the file")
        rows = json.loads(result.stdout)
        if not rows or not isinstance(rows[0], dict):
            raise ValueError("ExifTool returned no metadata record")
        if rows[0].get("ExifTool:Error"):
            raise ValueError(str(rows[0]["ExifTool:Error"]))
        return from_tags(rows[0], self.zone)
