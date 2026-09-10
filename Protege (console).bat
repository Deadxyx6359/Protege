@echo off
REM Launch Protege with a console attached, so a crash leaves its traceback on
REM screen instead of the window simply vanishing.
cd /d "%~dp0"
python shell.py
echo.
echo Protege exited with code %ERRORLEVEL%.
pause
