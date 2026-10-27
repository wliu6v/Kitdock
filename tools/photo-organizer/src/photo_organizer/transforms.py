"""Future output transformations; organization currently preserves original bytes."""

from pathlib import Path
from typing import Protocol


class MediaTransform(Protocol):
    """Write a derivative to a new path; never modify the source or its metadata."""

    def convert(self, source: Path, destination: Path) -> None: ...


# TODO: Add HEIC -> JPEG conversion with explicit quality and metadata preservation.
# TODO: Add JPEG compression, orientation normalization, and color-profile handling.
# TODO: Integrate derivatives with group naming, progress, and reports before exposing UI.
# TODO: Keep originals and Live Photo/AAE companions alongside optional derivatives.
