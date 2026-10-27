#!/bin/sh
# Launch the local virtual environment without relying on the caller's directory.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo 'Create the environment first; see README.md.'
    read -r answer
    exit 1
fi
if [ -x bin/exiftool/exiftool ]; then
    exec .venv/bin/python -m photo_organizer --gui --exiftool "$PWD/bin/exiftool/exiftool" "$@"
fi
exec .venv/bin/python -m photo_organizer --gui "$@"
