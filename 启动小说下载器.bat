@echo off
setlocal
cd /d "%~dp0"
if exist ".novel_venv\Scripts\python.exe" (
    ".novel_venv\Scripts\python.exe" "novel_downloader.py"
) else (
    python "novel_downloader.py"
)
if errorlevel 1 pause
