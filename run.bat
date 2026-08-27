@echo off
cd /d "%~dp0"
echo Running from: %CD%
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" web_app.py
) else (
    echo [WARNING] .venv not found, falling back to system Python
    py -3.12 web_app.py
)
pause
