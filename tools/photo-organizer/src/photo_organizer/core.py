"""Shared, copy-only organization engine for CLI and GUI."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .location import Geocoder
from .metadata import IMAGES, SIDECARS, SUPPORTED, ExifTool, Metadata, clean_label, parse_date


class MetadataReader(Protocol):
    def read(self, path: Path) -> Metadata: ...


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Options:
    inputs: tuple[Path, ...]
    output: Path | None = None
    dry_run: bool = False
    missing_time: str = "mtime"
    exiftool: str = "exiftool"
    utc_offset: str = "+08:00"
    geocode_url: str = ""


@dataclass(frozen=True)
class Progress:
    phase: str
    done: int
    total: int
    message: str


@dataclass
class Result:
    output: Path
    total: int = 0
    copied: int = 0
    skipped: int = 0
    planned: int = 0
    errors: int = 0
    ignored: int = 0
    cancelled: bool = False
    report: Path | None = None
    records: list[dict] = field(default_factory=list)


def default_output(first: Path) -> Path:
    first = first.expanduser().resolve()
    return first.with_name(first.name + "_整理") if first.name else first / "照片_整理"


def validate(options: Options) -> tuple[list[Path], Path]:
    if not options.inputs:
        raise ValueError("Select at least one input directory")
    if options.missing_time not in {"mtime", "skip"}:
        raise ValueError("Invalid missing-time policy")
    roots = list(dict.fromkeys(p.expanduser().resolve() for p in options.inputs))
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Input directory does not exist: {root}")
    output = (options.output or default_output(roots[0])).expanduser().resolve()
    for root in roots:
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError("Input and output directories must not contain one another")
    if output.exists() and not output.is_dir():
        raise ValueError("Output is not a directory")
    return roots, output


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def sha256(path: Path, cancel: threading.Event) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def copy_verified(source: Path, target: Path, expected: str, cancel: threading.Event) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".photo-copy-", dir=target.parent)
    temporary = Path(name)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as writer, source.open("rb") as reader:
            while chunk := reader.read(1024 * 1024):
                check_cancel(cancel)
                writer.write(chunk)
                digest.update(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if digest.hexdigest() != expected:
            raise ValueError("Source changed during copying; no output published")
        if sha256(temporary, cancel) != expected:
            raise ValueError("Output checksum verification failed")
        shutil.copystat(source, temporary)
        check_cancel(cancel)
        # Hard-link publication is atomic and fails if a target already exists.
        # Unlike replace(), it cannot overwrite a file created by another program.
        try:
            os.link(temporary, target)
        except OSError as exc:
            unsupported = {errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV}
            if exc.errno not in unsupported:
                raise
            # exFAT has no hard links. Exclusive creation still prevents overwrite;
            # the ledger lets the next run distinguish completed companion files.
            with target.open("xb") as writer:
                try:
                    with temporary.open("rb") as reader:
                        while chunk := reader.read(1024 * 1024):
                            check_cancel(cancel)
                            writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                except BaseException:
                    writer.close()
                    target.unlink(missing_ok=True)
                    raise
            if sha256(target, threading.Event()) != expected:
                target.unlink(missing_ok=True)
                raise ValueError("Published output checksum verification failed")
            shutil.copystat(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def output_lock(output: Path, dry_run: bool):
    if dry_run:
        yield
        return
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".photo-organizer.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(f"Output is locked. Check for another run before removing {lock}") from exc
    try:
        with handle:
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
            yield
    finally:
        lock.unlink(missing_ok=True)


def write_json(path: Path, data: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".photo-json-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def filename_date(path: Path) -> datetime | None:
    match = re.search(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[T _-]?([0-2]\d)[-_:]?([0-5]\d)[-_:]?([0-5]\d)(?!\d)", path.stem)
    return parse_date("{}-{}-{}T{}:{}:{}".format(*match.groups())) if match else None


def discover(roots: list[Path], cancel: threading.Event, emit: Callable[[Progress], None]):
    paths: set[Path] = set()
    ignored = 0
    for root in roots:
        def walk_error(error: OSError):
            raise error
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            check_cancel(cancel)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if name.startswith(".") or path.is_symlink() or path.suffix.lower() not in SUPPORTED or not path.is_file():
                    ignored += 1
                    continue
                paths.add(path)
            emit(Progress("scan", len(paths), 0, str(directory)))
    return sorted(paths, key=lambda p: (str(p).casefold(), str(p))), ignored


def group_files(paths: list[Path], metadata: dict[Path, Metadata]) -> list[list[Path]]:
    groups: dict[tuple, list[Path]] = defaultdict(list)
    # Start with same-directory/same-stem groups to retain MOV/AAE companions.
    for path in paths:
        groups[(path.parent, path.stem.casefold())].append(path)
    merged: dict[tuple, list[Path]] = defaultdict(list)
    for key, members in groups.items():
        ids = {metadata[p].content_id for p in members if p in metadata and metadata[p].content_id}
        # Content IDs can join differently named Live Photo assets in one directory.
        merge_key = (key[0], "id", next(iter(ids))) if len(ids) == 1 else (key[0], "stem", key[1])
        merged[merge_key].extend(members)
    return list(merged.values())


def organize(options: Options, progress: Callable[[Progress], None] = lambda _: None,
             cancel: threading.Event | None = None, reader: MetadataReader | None = None) -> Result:
    cancel = cancel or threading.Event()
    roots, output = validate(options)
    reader = reader or ExifTool(options.exiftool, options.utc_offset)
    result = Result(output)
    with output_lock(output, options.dry_run):
        ledger_path = output / ".photo-groups.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        if not isinstance(ledger, dict) or any(not isinstance(v, dict) for v in ledger.values()):
            raise ValueError("Invalid group ledger")
        geocoder = Geocoder(options.geocode_url, None if options.dry_run else output / ".location-cache.json") if options.geocode_url else None
        report_handle = None
        if not options.dry_run:
            result.report = output / f".photo-report-{uuid.uuid4().hex}.jsonl"
            report_handle = result.report.open("x", encoding="utf-8")

        def record(row: dict):
            result.records.append(row)
            if report_handle:
                report_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                report_handle.flush()

        try:
            paths, result.ignored = discover(roots, cancel, progress)
            result.total = len(paths)
            metadata: dict[Path, Metadata] = {}
            failures: dict[Path, str] = {}
            for i, path in enumerate(paths, 1):
                check_cancel(cancel)
                progress(Progress("metadata", i - 1, result.total, str(path)))
                try:
                    metadata[path] = reader.read(path)
                except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
                    failures[path] = str(exc)
                progress(Progress("metadata", i, result.total, str(path)))
            occupied: dict[str, dict[str, Path]] = defaultdict(dict)
            if output.exists():
                for path in output.iterdir():
                    occupied[path.stem.casefold()][path.suffix.casefold()] = path
            processed = 0
            virtual_groups: dict[str, dict[str, str]] = {}
            for group in group_files(paths, metadata):
                check_cancel(cancel)
                # Ambiguous groups are left untouched instead of inventing associations.
                extensions = [p.suffix.lower() for p in group]
                ids = {metadata[p].content_id for p in group if p in metadata and metadata[p].content_id}
                group_error = "Ambiguous companion group (duplicate extensions or conflicting content IDs)" if len(set(extensions)) != len(extensions) or len(ids) > 1 else ""
                if group_error or any(p in failures for p in group):
                    for path in group:
                        result.errors += 1
                        record({"source": str(path), "status": "error", "reason": group_error or failures.get(path, "Companion metadata could not be read")})
                        processed += 1
                        progress(Progress("copy", processed, result.total, str(path)))
                    continue
                preferred = sorted(group, key=lambda p: (p.suffix.lower() not in IMAGES, p.suffix.lower() in SIDECARS, str(p)))
                chosen = next((p for p in preferred if metadata[p].captured), preferred[0])
                meta = metadata[chosen]
                captured, time_source = meta.captured, meta.time_source
                uncertain = False
                if captured is None:
                    for path in preferred:
                        captured = filename_date(path)
                        if captured:
                            time_source = "filename"
                            break
                if captured is None and options.missing_time == "mtime":
                    captured = datetime.fromtimestamp(chosen.stat().st_mtime)
                    time_source, uncertain = "file_mtime", True
                if captured is None:
                    for path in group:
                        result.skipped += 1
                        record({"source": str(path), "status": "skipped", "reason": "Missing capture time"})
                        processed += 1
                        progress(Progress("copy", processed, result.total, str(path)))
                    continue
                location = next((metadata[p].location for p in preferred if metadata[p].location), "")
                coordinates = next((metadata[p].coordinates for p in preferred if metadata[p].coordinates), None)
                warnings = [metadata[p].warning for p in group if metadata[p].warning]
                if uncertain:
                    warnings.append("No capture time found; using file modification time")
                if len(group) > 1:
                    warnings.append("Companions share the preferred image timestamp; AAE edit application is not guaranteed")
                if not location and coordinates and geocoder:
                    try:
                        location = geocoder.lookup(coordinates)
                    except (OSError, ValueError) as exc:
                        warnings.append(f"Location lookup failed: {exc}")
                base = captured.strftime("%Y%m%d_%H%M%S")
                if uncertain:
                    base += "_时间待确认"
                if location:
                    base += "_" + clean_label(location)
                try:
                    hashes = {p: sha256(p, cancel) for p in group}
                    signature = {p.suffix.lower(): hashes[p] for p in group}
                    index = 1
                    while True:
                        stem = base if index == 1 else f"{base}_{index:02d}"
                        existing = occupied.get(stem.casefold())
                        if existing is None:
                            already = False
                            break
                        if options.dry_run and virtual_groups.get(stem.casefold()) == signature:
                            already = True
                            break
                        # Compare the whole companion set so unrelated MOV/JPG files
                        # with the same timestamp cannot silently become a pair.
                        recoverable = ledger.get(stem.casefold()) == signature
                        if (set(existing) == set(extensions) or (recoverable and set(existing) <= set(extensions))) and all(
                            p_existing.is_file() and not p_existing.is_symlink()
                            and sha256(p_existing, cancel) == signature[ext]
                            for ext, p_existing in existing.items()
                        ):
                            already = True
                            break
                        index += 1
                    targets = {p: output / (stem + p.suffix.lower()) for p in group}
                    existing_targets = dict(occupied.get(stem.casefold(), {})) if already else {}
                    if options.dry_run:
                        virtual_groups[stem.casefold()] = signature
                    if not options.dry_run:
                        ledger[stem.casefold()] = signature
                        write_json(ledger_path, ledger)
                    occupied[stem.casefold()] = {**{p.suffix.lower(): target for p, target in targets.items()}, **existing_targets}
                    for path in group:
                        check_cancel(cancel)
                        target = occupied[stem.casefold()][path.suffix.lower()]
                        row = {"source": str(path), "destination": str(target), "captured_at": captured.isoformat(),
                               "time_source": time_source, "location": location, "sha256": hashes[path], "warnings": warnings}
                        try:
                            if path.suffix.lower() in existing_targets:
                                result.skipped += 1
                                row["status"] = "identical"
                            elif options.dry_run:
                                result.planned += 1
                                row["status"] = "planned"
                            else:
                                copy_verified(path, target, hashes[path], cancel)
                                result.copied += 1
                                row["status"] = "copied"
                        except (OSError, ValueError) as exc:
                            result.errors += 1
                            row.update(status="error", reason=str(exc))
                        record(row)
                        processed += 1
                        progress(Progress("copy", processed, result.total, f"{path.name} → {target.name}"))
                except (OSError, ValueError) as exc:
                    for path in group:
                        result.errors += 1
                        record({"source": str(path), "status": "error", "reason": str(exc)})
                        processed += 1
                        progress(Progress("copy", processed, result.total, str(path)))
        except Cancelled:
            result.cancelled = True
        finally:
            if report_handle:
                report_handle.close()
    progress(Progress("done", result.copied + result.skipped + result.planned + result.errors, result.total, "Cancelled" if result.cancelled else "Finished"))
    return result
