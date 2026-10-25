@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Three additional reactions through REAL AI parsing and HYSYS execution.
echo Feed: 300 kmol/h, 300 C, 1000 kPa absolute. Confirm adiabatic and zero pressure drop.
choice /C YN /M "Confirm these modeling assumptions and start"
if errorlevel 2 exit /b 2
".venv\Scripts\python.exe" scripts\run_demo_checks.py --scenario generalization --require-ai --require-hysys --confirm-demo-assumptions
echo Preserve the acceptance report printed above.
pause
