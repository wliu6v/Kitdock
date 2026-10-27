@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create the environment first; see README.md.
    pause
    exit /b 1
)
if exist "bin\exiftool.exe" (
    ".venv\Scripts\python.exe" -m photo_organizer --gui --exiftool "%CD%\bin\exiftool.exe" %*
) else (
    ".venv\Scripts\python.exe" -m photo_organizer --gui %*
)
