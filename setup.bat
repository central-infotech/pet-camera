@echo off
echo ============================================
echo  Pet Camera - Initial Setup
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Create venv
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate and install
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -r server\requirements.txt

REM Create directories
if not exist "certs" mkdir certs
if not exist "logs" mkdir logs
if not exist "snapshots" mkdir snapshots

echo.
echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo Next steps:
echo   1. Set environment variable: set PET_CAMERA_TOKEN=your-secret-token
echo   2. Place TLS certificates in certs\ directory
echo   3. Run: venv\Scripts\python.exe run.py
echo.
pause
