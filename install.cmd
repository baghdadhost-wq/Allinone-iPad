@echo off
rem Double-click or run from cmd: installs everything Allinone needs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
