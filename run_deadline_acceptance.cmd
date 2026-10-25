@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Installing the narrow HYSYS checkbox bridge in the existing project environment.
".venv\Scripts\python.exe" -m pip install "pywinauto>=0.6.9"
if errorlevel 1 (
  echo Optional UI bridge installation failed. Continuing with explicit operator guidance.
)
echo Keep the remote desktop unlocked. Avoid clicking HYSYS while the bridge locates its controls.
echo If HYSYS ACTION is printed, open the CURRENT reactor Design/Parameters page
echo and uncheck Act as a Separator When Cannot Solve, leaving the script running.
call run_full_acceptance.cmd
