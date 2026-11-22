@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m assistant --list-devices > devices.txt 2>&1
