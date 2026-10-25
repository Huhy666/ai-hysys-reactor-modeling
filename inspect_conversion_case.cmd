@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Reading a temporary copy of the latest saved failed conversion case.
echo This does not rerun AI parsing or rebuild the reactor.
".venv\Scripts\python.exe" scripts\inspect_conversion_case.py
echo.
echo Keep the printed case-readback.json file and send its contents for diagnosis.
pause
