@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Mandatory scenarios: REAL AI parsing, REAL HYSYS, balance checks and downloads.
echo Confirm equal xylene selectivity, adiabatic/zero-drop toluene operation,
echo and reforming feed 1000 kmol/h methane + 2700 kmol/h water, 8000 hours/year,
echo zero pressure drop, and use of available HYSYS thermodynamic equilibrium data.
choice /C YN /M "Confirm these modeling assumptions and start"
if errorlevel 2 exit /b 2
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_remote.ps1
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" scripts\run_demo_checks.py --scenario all --require-ai --require-hysys --confirm-demo-assumptions
if errorlevel 1 goto failed
echo Mandatory API acceptance passed. Browser rehearsal and generalization remain required.
pause
exit /b 0
:failed
echo Check failed. Preserve the acceptance report directory printed above.
pause
exit /b 1
