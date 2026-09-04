@echo off
powershell.exe -ExecutionPolicy Bypass -Command "Unblock-File -Path '%~dp0setup.ps1'" 2>nul
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup.ps1"
pause
