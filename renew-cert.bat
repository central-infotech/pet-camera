@echo off
REM Pet Camera - TLS Certificate Renewal
REM Schedule this in Task Scheduler to run monthly.

echo [%date% %time%] Starting certificate renewal...

REM Get machine name from existing cert files
set CERT_DIR=%~dp0certs
for %%f in (%CERT_DIR%\*.crt) do (
    set CERT_NAME=%%~nf
)

if "%CERT_NAME%"=="" (
    echo [ERROR] No existing certificate found in %CERT_DIR%
    exit /b 1
)

echo Renewing certificate for %CERT_NAME%...
tailscale cert --cert-file "%CERT_DIR%\%CERT_NAME%.crt" --key-file "%CERT_DIR%\%CERT_NAME%.key" %CERT_NAME%

if errorlevel 1 (
    echo [ERROR] Certificate renewal failed.
    exit /b 1
)

echo Certificate renewed. Restarting service...
REM Find NSSM
set NSSM=nssm
nssm version >nul 2>&1
if errorlevel 1 (
    for /f "delims=" %%i in ('where /r "%LOCALAPPDATA%\Microsoft\WinGet" nssm.exe 2^>nul') do set NSSM=%%i
)
"%NSSM%" restart PetCameraServer

echo [%date% %time%] Certificate renewal complete.
