@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Toluene HYSYS diagnostic - this runs REAL HYSYS in this Windows session.
echo Assumptions: equal o/m/p-xylene selectivity; adiabatic operation; zero pressure drop.
echo This is structured-input diagnosis. Natural-language acceptance is a separate step.
choice /C YN /M "Confirm these modeling assumptions and start"
if errorlevel 2 exit /b 2
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_remote.ps1
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" scripts\run_demo_checks.py --scenario toluene --require-hysys --confirm-demo-assumptions
if errorlevel 1 goto failed
echo Diagnostic passed. Save the report and proceed to natural-language acceptance.
pause
exit /b 0
:failed
echo Check failed. Preserve the acceptance report directory printed above.
pause
exit /b 1
