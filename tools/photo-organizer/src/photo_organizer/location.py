"""Optional reverse geocoding against a user-configured Nominatim-compatible service."""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .metadata import clean_label


class Geocoder:
    def __init__(self, endpoint: str, cache_path: Path | None = None):
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("Geocoder URL must be an HTTPS reverse endpoint without query or fragment")
        if parsed.hostname.lower() == "nominatim.openstreetmap.org":
            raise ValueError("Use a self-hosted or commercial endpoint authorized for batch reverse geocoding")
        self.endpoint = endpoint
        self.cache_path = cache_path
        self.cache: dict[str, str] = {}
        if cache_path and cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(self.cache, dict):
                raise ValueError("Invalid geocoder cache")
        self.last_request = 0.0

    def lookup(self, coordinates: tuple[float, float]) -> str:
        # Rounded keys reduce repeated lookups; coordinates are never part of filenames.
        key = self.endpoint + "|" + ",".join(f"{n:.4f}" for n in coordinates)
        if key in self.cache:
            return clean_label(str(self.cache[key]))
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        query = urllib.parse.urlencode({
            "lat": coordinates[0], "lon": coordinates[1], "format": "jsonv2",
            "addressdetails": 1, "accept-language": "zh-CN", "zoom": 16,
        })
        request = urllib.request.Request(self.endpoint + "?" + query, headers={
            "User-Agent": "KitdockPhotoOrganizer/0.1", "Accept": "application/json",
        })
        self.last_request = time.monotonic()
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        if payload.get("error"):
            raise ValueError(str(payload["error"]))
        address = payload.get("address", {})
        city = next((address[k] for k in ("city", "town", "municipality", "county", "state") if address.get(k)), "")
        area = next((address[k] for k in ("neighbourhood", "quarter", "suburb", "village", "city_district") if address.get(k)), "")
        label = clean_label(str(city) + (str(area) if area != city else ""))
        self.cache[key] = label
        if self.cache_path:
            # The organizer holds the destination lock for the whole run.
            descriptor, name = tempfile.mkstemp(prefix=".location-", dir=self.cache_path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(self.cache, handle, ensure_ascii=False)
                temporary.replace(self.cache_path)
            finally:
                temporary.unlink(missing_ok=True)
        return label
