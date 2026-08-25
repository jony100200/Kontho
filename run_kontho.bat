@echo off
REM Launch Kontho with the root venv. pythonw keeps the console window away.
setlocal
set ROOT=%~dp0
set VENV=D:\KSAppDev\.venv\Scripts
REM `-m kontho` resolves against the working directory, so anchor it here.
cd /d "%ROOT%"
if exist "%VENV%\pythonw.exe" (
    start "" "%VENV%\pythonw.exe" -m kontho %*
) else (
    echo Root venv not found at %VENV% - falling back to PATH python.
    start "" pythonw -m kontho %*
)
endlocal
