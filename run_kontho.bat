@echo off
REM Launch Kontho silently in the background (pythonw prevents console popup).
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

REM Check local project virtualenv, parent workspace virtualenv, or system PATH
if exist "%ROOT%.venv\Scripts\pythonw.exe" (
    start "" "%ROOT%.venv\Scripts\pythonw.exe" -m kontho %*
) else if exist "%ROOT%venv\Scripts\pythonw.exe" (
    start "" "%ROOT%venv\Scripts\pythonw.exe" -m kontho %*
) else if exist "%ROOT%..\.venv\Scripts\pythonw.exe" (
    start "" "%ROOT%..\.venv\Scripts\pythonw.exe" -m kontho %*
) else (
    start "" pythonw -m kontho %*
)
endlocal
