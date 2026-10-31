@echo off
echo ==================================================
echo   DataSetu (डेटासेतु) - Windows Launch Script
echo ==================================================

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python 3 was not found in PATH!
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo (Make sure to check "Add Python to PATH" during installation)
    pause
    exit /b 1
)

python --version

if not exist .venv (
    echo Creating virtual environment in .venv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Checking and installing dependencies...
pip install -q -r requirements.txt
pip install -q -e .

echo.
echo ==================================================
echo   🚀 Launching DataSetu Engine on http://localhost:8000
echo    - Web UI:       http://localhost:8000/
echo    - Swagger Docs: http://localhost:8000/docs
echo    - REST API:     http://localhost:8000/v1/data
echo ==================================================
echo.

python -m datasetu.cli serve demo\bharat_governance_master_2026.csv --port 8000 --cdc
pause
