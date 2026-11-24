@echo off
rem Allinone launcher for Windows (cmd and PowerShell).  Usage: allinone [command]
setlocal
set "AIO_PY="
where py >nul 2>nul && set "AIO_PY=py -3"
if not defined AIO_PY (
  where python >nul 2>nul && set "AIO_PY=python"
)
if not defined AIO_PY (
  echo [Allinone] Python 3.10+ was not found. Run install.cmd first.
  exit /b 1
)
%AIO_PY% "%~dp0allinone.py" %*
exit /b %ERRORLEVEL%
