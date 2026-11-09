@echo off
rem Installs SolidSmurfs for this Windows user (no admin): see install-solidsmurfs.ps1 beside this file.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-solidsmurfs.ps1" %*
echo.
pause
