@echo off
echo ============================================
echo  Pet Camera - NSSM Service Installation
echo ============================================
echo.

REM Check admin
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Run this script as Administrator.
    pause
    exit /b 1
)

REM Find NSSM
set NSSM=nssm
nssm version >nul 2>&1
if errorlevel 1 (
    REM Try winget install location
    for /f "delims=" %%i in ('where /r "%LOCALAPPDATA%\Microsoft\WinGet" nssm.exe 2^>nul') do set NSSM=%%i
)
"%NSSM%" version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] NSSM is not installed or not in PATH.
    echo Install via: winget install NSSM.NSSM
    pause
    exit /b 1
)
echo Found NSSM: %NSSM%

REM Check token (process-level or machine-level)
if "%PET_CAMERA_TOKEN%"=="" (
    for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PET_CAMERA_TOKEN 2^>nul ^| findstr PET_CAMERA_TOKEN') do set PET_CAMERA_TOKEN=%%b
)
if "%PET_CAMERA_TOKEN%"=="" (
    echo [ERROR] PET_CAMERA_TOKEN environment variable is not set.
    echo Set it first: setx /M PET_CAMERA_TOKEN "your-secret-token"
    pause
    exit /b 1
)

set SERVICE_NAME=PetCameraServer
set APP_DIR=%~dp0
REM Remove trailing backslash to prevent quote-escaping issues
if "%APP_DIR:~-1%"=="\" set APP_DIR=%APP_DIR:~0,-1%
set PYTHON=%APP_DIR%\venv\Scripts\python.exe
set SCRIPT=%APP_DIR%\run.py

REM Remove existing service if present
"%NSSM%" stop %SERVICE_NAME% >nul 2>&1
"%NSSM%" remove %SERVICE_NAME% confirm >nul 2>&1

REM Install service
echo Installing service: %SERVICE_NAME%
"%NSSM%" install %SERVICE_NAME% "%PYTHON%" "%SCRIPT%"
"%NSSM%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM%" set %SERVICE_NAME% DisplayName "Pet Camera Server"
"%NSSM%" set %SERVICE_NAME% Description "Pet camera streaming server with video and audio"
"%NSSM%" set %SERVICE_NAME% Start SERVICE_AUTO_START

REM Restart on failure (5s delay, max 3 times in 10 min)
"%NSSM%" set %SERVICE_NAME% AppThrottle 5000
"%NSSM%" set %SERVICE_NAME% AppRestartDelay 5000

REM Logging
"%NSSM%" set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\stdout.log"
"%NSSM%" set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\stderr.log"
"%NSSM%" set %SERVICE_NAME% AppStdoutCreationDisposition 4
"%NSSM%" set %SERVICE_NAME% AppStderrCreationDisposition 4
"%NSSM%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM%" set %SERVICE_NAME% AppRotateBytes 10485760

REM Run as current user (required for camera/microphone access)
"%NSSM%" set %SERVICE_NAME% ObjectName .\%USERNAME%
echo.
echo [IMPORTANT] You will be prompted to set the service logon password.
echo Run: "%NSSM%" set %SERVICE_NAME% ObjectName .\%USERNAME% YOUR_PASSWORD
echo Or use services.msc to set the logon account.

REM Environment variables
"%NSSM%" set %SERVICE_NAME% AppEnvironmentExtra PET_CAMERA_TOKEN=%PET_CAMERA_TOKEN% PET_CAMERA_ENV=production

echo.
echo Service installed successfully!
echo.
echo Commands:
echo   Start:   "%NSSM%" start %SERVICE_NAME%
echo   Stop:    "%NSSM%" stop %SERVICE_NAME%
echo   Restart: nssm restart %SERVICE_NAME%
echo   Status:  nssm status %SERVICE_NAME%
echo   Remove:  "%NSSM%" remove %SERVICE_NAME% confirm
echo.

"%NSSM%" start %SERVICE_NAME%
echo Service started.
pause
