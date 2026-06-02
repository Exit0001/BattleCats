@echo off
REM Quick start script for BCSFE Order System on Windows

echo.
echo ========================================
echo   BCSFE Order System - Quick Start
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

echo [OK] Python found
python --version
echo.

REM Create virtual environment if it doesn't exist
if not exist venv (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created
    echo.
)

REM Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install requirements
echo [INFO] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

REM Check if bcsfe is installed
echo [INFO] Checking bcsfe installation...
python -m bcsfe --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] bcsfe might not be properly installed
    echo Trying to install bcsfe...
    pip install bcsfe --upgrade
)
echo.

REM Start server
echo ========================================
echo   Starting BCSFE Order System...
echo ========================================
echo.
echo [URL] Open: http://localhost:8000/static/bcsfe-order.html
echo.
echo Press Ctrl+C to stop the server
echo.

python main.py

pause
