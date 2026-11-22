@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m assistant %*
if errorlevel 1 pause
