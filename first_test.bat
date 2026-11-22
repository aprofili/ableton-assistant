@echo off
cd /d "%~dp0"
(
  ".venv\Scripts\python.exe" -m assistant --check
  ".venv\Scripts\python.exe" -m assistant --text "create a loop region from measures 5 to 9, turn on the metronome and press play"
) > first_test.log 2>&1
