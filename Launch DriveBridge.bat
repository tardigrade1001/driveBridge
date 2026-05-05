@echo off
cd /d "%~dp0"

:: Try pythonw first (no console window), fall back to python
where pythonw >nul 2>&1
if %errorlevel% == 0 (
    start "" pythonw "%~dp0main.py"
) else (
    start "" python "%~dp0main.py"
)
