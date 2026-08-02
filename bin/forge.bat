@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
if "%PYTHON%"=="" set "PYTHON=python"

if "%PYTHONPATH%"=="" (
  set "PYTHONPATH=%PROJECT_ROOT%"
) else (
  set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"
)

"%PYTHON%" -m forge_cli %*
exit /b %ERRORLEVEL%
