"""Command line entry point."""

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

from .core import Options, organize


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect phone media without modifying originals.")
    parser.add_argument("inputs", nargs="*", type=Path, help="One or more source directories")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: sibling INPUT_整理)")
    parser.add_argument("--gui", action="store_true", help="Open the desktop window")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--missing-time", choices=["mtime", "skip"], default="mtime")
    parser.add_argument("--utc-offset", default="+08:00", help="Zone for UTC-only video times")
    parser.add_argument("--exiftool", default="exiftool", help="ExifTool executable path")
    parser.add_argument("--geocode-url", default="", help="Opt in to sending GPS to a configured HTTPS reverse endpoint")
    args = parser.parse_args(argv)
    options = Options(tuple(args.inputs), args.output, args.dry_run, args.missing_time,
                      args.exiftool, args.utc_offset, args.geocode_url)
    if args.gui or not args.inputs:
        try:
            from .gui import main as gui_main
        except ImportError:
            print('GUI dependencies missing. Run: python -m pip install -e ".[gui]"', file=sys.stderr)
            return 2
        return gui_main(options)
    cancel = threading.Event()
    old_handler = signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        def show(event):
            print(f"[{event.phase}] {event.done}/{event.total or '?'} {event.message}", file=sys.stderr)
        result = organize(options, progress=show, cancel=cancel)
        print(json.dumps({"output": str(result.output), "total": result.total, "copied": result.copied,
                          "identical_or_skipped": result.skipped, "planned": result.planned,
                          "errors": result.errors, "ignored": result.ignored, "cancelled": result.cancelled,
                          "report": str(result.report) if result.report else None}, ensure_ascii=False))
        if args.dry_run:
            for row in result.records:
                print(json.dumps(row, ensure_ascii=False))
        return 130 if result.cancelled else 1 if result.errors else 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, old_handler)
