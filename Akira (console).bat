@echo off
REM Launch Akira with a console attached, so a crash leaves its traceback on
REM screen instead of the window simply vanishing.
cd /d "%~dp0"
python shell.py
echo.
echo Akira exited with code %ERRORLEVEL%.
pause
