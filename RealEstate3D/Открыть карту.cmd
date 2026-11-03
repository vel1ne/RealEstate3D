@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "MAP_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%MAP_PYTHON%" (
    "%MAP_PYTHON%" -u "%~dp0scripts\serve_map.py" %*
    goto finish
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    py -3 -u "%~dp0scripts\serve_map.py" %*
    goto finish
)
python --version >nul 2>&1
if not errorlevel 1 (
    python -u "%~dp0scripts\serve_map.py" %*
    goto finish
)
echo Не найден Python 3. Сообщите об этом в чате проекта; устанавливать что-либо самостоятельно не нужно.
pause
exit /b 1

:finish
set "MAP_EXIT=%ERRORLEVEL%"
if not "%MAP_EXIT%"=="0" pause
exit /b %MAP_EXIT%
